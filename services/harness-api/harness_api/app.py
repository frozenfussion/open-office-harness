# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
import json
import logging
import sys
import time
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import UUID

import anyio
import httpx
import psycopg
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
)
from starlette.exceptions import HTTPException
from starlette.types import Receive, Scope, Send

from .auth import Auth
from .config import Settings
from .diagnostics import JsonFormatter
from .diagnostics import failure as record_failure
from .errors import ApiError, gateway_error
from .events import JobEvents, Kafka, Publisher, envelope
from .jobs import Jobs, download_path
from .store import MAX_THINKING_CHARS, Store
from .upstream import GatewayStream, Upstream

TITLE_TIMEOUT_SECONDS = 20
CHAT_PUBLISH_TIMEOUT_SECONDS = 12


class Empty(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Message(Empty):
    content: str = Field(min_length=1)
    tier: Annotated[StrictInt, Field(gt=0)] | None = None
    thinking: StrictBool = True

    @field_validator("content")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Content must not be blank")
        return value


class TierRequest(Empty):
    tier: Annotated[StrictInt, Field(gt=0)]
    reason: str | None = Field(default=None, max_length=300)


class SkillRequest(Empty):
    skill: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    reason: str | None = Field(default=None, max_length=300)


class Page(Empty):
    limit: int = Field(default=20, ge=1, le=100)
    before: UUID | None = None


def data(event: dict[str, Any]) -> str:
    return "data: " + json.dumps(event, separators=(",", ":")) + "\n\n"


class ChatResponse(StreamingResponse):
    def __init__(self, content: AsyncGenerator[str], stream: GatewayStream) -> None:
        super().__init__(
            content,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )
        self.chat_iterator = content
        self.gateway_stream = stream

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                try:
                    await self.chat_iterator.aclose()
                finally:
                    await self.gateway_stream.close()


def create_app(
    settings: Settings,
    store: Store | None = None,
    client: httpx.AsyncClient | None = None,
    publisher: Publisher | None = None,
    jobs: Jobs | None = None,
) -> FastAPI:
    http = client or httpx.AsyncClient(timeout=10, follow_redirects=False)
    database = store or Store(settings.database)
    auth = Auth(settings, http)
    upstream = Upstream(settings, http, auth)

    kafka = Kafka(settings) if publisher is None and settings.kafka_bootstrap else None
    bus = publisher or kafka
    notifications = JobEvents()
    job_store = jobs or Jobs(settings.database, upstream, bus, notifications)

    chat_tasks: set[asyncio.Task[None]] = set()

    async def publish_chat(
        role: str,
        content: str,
        conversation: UUID,
        message: UUID,
        correlation: UUID,
        user: str,
        tier: int,
        title: str | None = None,
    ) -> None:
        if not content or bus is None:
            return
        try:
            async with asyncio.timeout(CHAT_PUBLISH_TIMEOUT_SECONDS):
                await bus.publish(
                    "chat.messages",
                    envelope(
                        "chat.message",
                        str(correlation),
                        user,
                        {
                            "conversation_id": str(conversation),
                            "message_id": str(message),
                            "role": role,
                            "text": content[:20000],
                            "tier": tier,
                            "model_title": title,
                        },
                    ),
                )
        except Exception:
            record_failure(
                "kafka_error", "chat_publish_failed", correlation_id=str(correlation)
            )

    def schedule_chat(*args: Any) -> None:
        task = asyncio.create_task(publish_chat(*args))
        chat_tasks.add(task)
        task.add_done_callback(chat_tasks.discard)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        stop = asyncio.Event()
        task = (
            asyncio.create_task(kafka.serve(job_store.handle, stop)) if kafka else None
        )
        try:
            yield
        finally:
            stop.set()
            if task:
                await task
            if chat_tasks:
                await asyncio.gather(*chat_tasks)
            if client is None:
                await http.aclose()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.chat_tasks = chat_tasks
    app.state.kafka = kafka
    app.state.auth = auth
    app.state.upstream = upstream
    app.state.store = database
    app.state.jobs = job_store
    app.state.notifications = notifications

    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError) -> JSONResponse:
        if error.code == "unauthorized":
            event = "authentication_error"
        elif error.code in {
            "rights_unavailable",
            "tier_not_allowed",
            "no_tier",
            "not_approved",
            "tier_not_requestable",
            "already_requested",
            "too_soon",
            "too_many_requests",
        }:
            event = "rights_error"
        elif error.code in {
            "no_model",
            "rate_limited",
            "budget_exceeded",
            "unavailable",
        }:
            event = "gateway_error"
        else:
            event = "request_error"
        record_failure(event, error.code)
        return JSONResponse(error.body(), status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, error: RequestValidationError) -> JSONResponse:
        record_failure("request_error", "invalid_input")
        return JSONResponse(
            {"code": "invalid_input", "message": "Invalid input."}, status_code=400
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        record_failure(
            "request_error",
            "not_found" if error.status_code == 404 else "invalid_input",
        )
        return JSONResponse(
            {
                "code": "not_found" if error.status_code == 404 else "invalid_input",
                "message": "Route not found."
                if error.status_code == 404
                else "Invalid request.",
            },
            status_code=error.status_code,
        )

    @app.exception_handler(psycopg.Error)
    async def db_error(request: Request, error: psycopg.Error) -> JSONResponse:
        record_failure("database_error", "unavailable")
        return JSONResponse(
            {
                "code": "unavailable",
                "message": "Conversation storage is unavailable. Try again.",
            },
            status_code=503,
        )

    async def user(request: Request) -> dict[str, Any]:
        return await auth.verify(request.headers.get("authorization"))

    User = Annotated[dict[str, Any], Depends(user)]

    def query(request: Request, allowed: set[str] | None = None) -> None:
        allowed = allowed or set()
        keys = list(request.query_params.keys())
        if set(keys) - allowed or any(
            len(request.query_params.getlist(key)) != 1 for key in keys
        ):
            raise ApiError(400, "invalid_input", "Invalid query parameters.")

    @app.get("/health")
    async def health(request: Request) -> dict[str, str]:
        query(request)
        await database.health()
        return {"status": "ok"}

    @app.get("/api/me")
    async def me(request: Request, claims: User) -> dict[str, Any]:
        query(request)
        access = await upstream.observe(claims)
        rights, skills = await upstream.permissions(claims["sub"])
        name = claims.get("name", "")
        return {
            "user_id": claims["sub"],
            "access": access,
            "name": name if isinstance(name, str) else "",
            "chat_tiers": rights.chat_tiers,
            "chat_tier_titles": rights.chat_tier_titles,
            "chat_tier_thinking_switch": rights.chat_tier_thinking_switch,
            "requestable_tiers": [
                entry.model_dump() for entry in rights.requestable_tiers
            ],
            "requestable_skills": [
                entry.model_dump() for entry in rights.requestable_skills
            ],
            "skills": [{"name": skill.name, "title": skill.title} for skill in skills],
        }

    @app.post("/api/tier-requests", status_code=201)
    async def request_tier(
        request: Request, body: TierRequest, claims: User
    ) -> dict[str, Any]:
        query(request)
        return await upstream.request_tier(claims["sub"], body.tier, body.reason)

    @app.post("/api/skill-requests", status_code=201)
    async def request_skill(
        request: Request, body: SkillRequest, claims: User
    ) -> dict[str, Any]:
        query(request)
        return await upstream.request_skill(claims["sub"], body.skill, body.reason)

    @app.post("/api/conversations", status_code=201)
    async def create(request: Request, claims: User, body: Empty) -> dict[str, UUID]:
        query(request)
        return {"id": await database.create(claims["sub"])}

    @app.get("/api/conversations")
    async def listing(request: Request, claims: User) -> list[dict[str, Any]]:
        query(request, {"limit", "before"})
        try:
            page = Page.model_validate(dict(request.query_params))
        except ValueError:
            raise ApiError(400, "invalid_input", "Invalid pagination.") from None
        return await database.listing(claims["sub"], page.limit, page.before)

    @app.get("/api/conversations/{id}")
    async def conversation(request: Request, id: UUID, claims: User) -> dict[str, Any]:
        query(request)
        return await database.conversation(id, claims["sub"])

    async def make_title(
        identifier: UUID, user_id: str, message_id: UUID, tier: int, correlation: UUID
    ) -> str | None:
        try:
            with anyio.fail_after(TITLE_TIMEOUT_SECONDS):
                source = await database.title_source(identifier, user_id, message_id)
                if source is None:
                    return None
                await upstream.check(user_id, tier)
                title = await upstream.title(
                    user_id, tier, source["question"], source["answer"], correlation
                )
                if not await database.set_title(
                    identifier, user_id, title, source["question"][:60]
                ):
                    return None
                return title
        except ApiError as error:
            record_failure("title_failed", error.code)
        except (
            httpx.HTTPError,
            ValueError,
            KeyError,
            TypeError,
            psycopg.Error,
            TimeoutError,
        ):
            record_failure("title_failed", "unavailable")
        return None

    async def browser_stream(
        stream: GatewayStream,
        first: dict[str, Any],
        identifier: UUID,
        user_id: str,
        tier: int,
        note: str | None,
        history: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        thinking: bool,
        correlation: UUID,
    ) -> AsyncGenerator[str]:
        content = ""
        thinking_text = ""
        outcome = "failed"
        metadata: dict[str, Any] = {}
        saved = False
        calls: list[dict[str, Any]] = []
        job_ids: list[str] = []
        job_started = False
        rounds = 0
        pinned: str | None = None
        round_content = ""
        try:
            event = first
            while True:
                match event["type"]:
                    case "delta":
                        content += event["text"]
                        round_content += event["text"]
                        yield data(event)
                    case "thinking":
                        if len(thinking_text) < MAX_THINKING_CHARS:
                            thinking_text += event["text"][
                                : MAX_THINKING_CHARS - len(thinking_text)
                            ]
                        yield data(event)
                    case "tool_call":
                        calls.append(
                            {key: event[key] for key in ("id", "name", "arguments")}
                        )
                    case "completed":
                        if pinned is not None and event["model_entry_id"] != pinned:
                            raise ValueError("Tool turn changed model entry")
                        if calls:
                            if rounds >= 2:
                                sentence = "Tool limit reached for this message."
                                content += sentence
                                yield data({"type": "delta", "text": sentence})
                                calls.clear()
                            else:
                                rounds += 1
                                entry = event["model_entry_id"]
                                if pinned is not None and entry != pinned:
                                    raise ValueError("Tool turn changed model entry")
                                pinned = entry
                                history.append(
                                    {
                                        "role": "assistant",
                                        "content": round_content,
                                        "tool_calls": calls,
                                        "reasoning_state": event.get("reasoning_state"),
                                    }
                                )
                                for tool in calls:
                                    result, job = await job_store.start(
                                        user_id, identifier, tool
                                    )
                                    if job:
                                        job_ids.append(job["job_id"])
                                        job_started = job_started or job["status"] in {
                                            "queued",
                                            "awaiting_approval",
                                        }
                                        yield data(job)
                                    history.append(
                                        {
                                            "role": "tool",
                                            "tool_call_id": tool["id"],
                                            "content": json.dumps(result),
                                        }
                                    )
                                calls = []
                                round_content = ""
                                content = ""
                                await stream.close()
                                stream = await upstream.open(
                                    user_id,
                                    tier,
                                    history,
                                    tools,
                                    thinking,
                                    correlation,
                                    pinned,
                                )
                                event = await anext(stream.events)
                                continue
                        metadata = event
                        outcome = "completed"
                        message_id = await database.append(
                            identifier,
                            user_id,
                            "assistant",
                            content,
                            outcome,
                            tier,
                            metadata,
                            note,
                            thinking=thinking_text or None,
                        )
                        saved = True
                        if job_ids:
                            await job_store.attach(job_ids, message_id)
                        schedule_chat(
                            "assistant",
                            content,
                            identifier,
                            message_id,
                            correlation,
                            user_id,
                            tier,
                            event["model_title"],
                        )
                        yield data(
                            {
                                "type": "completed",
                                "message_id": str(message_id),
                                "tier": tier,
                                "model_title": event["model_title"],
                                "usage": event["usage"],
                                "note": note,
                                "thinking_applied": event["thinking_applied"],
                            }
                        )
                        title = await make_title(
                            identifier, user_id, message_id, tier, correlation
                        )
                        if title is not None:
                            yield data(
                                {
                                    "type": "title",
                                    "conversation_id": str(identifier),
                                    "title": title,
                                }
                            )
                        return
                    case "failed":
                        raise gateway_error(event["error"]["code"], tier)
                event = await anext(stream.events)
        except psycopg.Error:
            record_failure("database_error", "unavailable")
            yield data(
                {"type": "failed", "error": gateway_error("unavailable", tier).body()}
            )
        except (
            ApiError,
            httpx.HTTPError,
            ValueError,
            KeyError,
            TypeError,
            StopAsyncIteration,
        ) as error:
            error_response = (
                error
                if isinstance(error, ApiError)
                else gateway_error("unavailable", tier)
            )
            record_failure("gateway_error", error_response.code, tier)
            body = error_response.body()
            if job_started:
                body["message"] = (
                    "The job has started, but the model could not finish its answer."
                )
            yield data({"type": "failed", "error": body})
        finally:
            # A browser disconnect cancels the generator; keep its partial answer.
            with anyio.CancelScope(shield=True):
                try:
                    await stream.close()
                finally:
                    if not saved:
                        try:
                            failed_message = await database.append(
                                identifier,
                                user_id,
                                "assistant",
                                content,
                                "failed",
                                tier,
                                metadata,
                                note,
                                thinking=thinking_text or None,
                            )
                            if job_ids:
                                await job_store.attach(job_ids, failed_message)
                        except psycopg.Error:
                            record_failure("database_error", "unavailable")
                            raise

    @app.post("/api/conversations/{id}/messages")
    async def send(
        request: Request, id: UUID, body: Message, claims: User
    ) -> StreamingResponse:
        query(request)
        user_id = claims["sub"]
        await database.conversation(id, user_id)
        rights, skills = await upstream.permissions(user_id)
        tiers = rights.chat_tiers
        if body.tier is None and not tiers:
            raise ApiError(
                403, "no_tier", "You have no chat tier yet. An admin can grant one."
            )
        tier = body.tier if body.tier is not None else tiers[0]
        await upstream.check(user_id, tier)
        tools = upstream.tools(skills)
        history = await database.history(id)
        history.append({"role": "user", "content": body.content})
        correlation = await database.append(
            id, user_id, "user", body.content, "completed", tier
        )
        schedule_chat("user", body.content, id, correlation, correlation, user_id, tier)
        note = None
        stream = None
        try:
            try:
                stream = await upstream.open(
                    user_id, tier, history, tools, body.thinking, correlation
                )
            except ApiError as error:
                lower = [value for value in tiers if value < tier]
                if error.code != "budget_exceeded" or not lower:
                    raise
                record_failure("gateway_error", error.code, tier)
                original = tier
                tier = lower[0]
                await upstream.check(user_id, tier)
                note = (
                    f"tier {original} is over its daily budget; "
                    f"answered with tier {tier}"
                )
                stream = await upstream.open(
                    user_id, tier, history, tools, body.thinking, correlation
                )
            first = await anext(stream.events)
            if first["type"] == "failed":
                raise gateway_error(first["error"]["code"], tier)
        except (
            ApiError,
            httpx.HTTPError,
            ValueError,
            KeyError,
            TypeError,
            StopAsyncIteration,
        ) as error:
            if stream is not None:
                await stream.close()
            await database.append(
                id, user_id, "assistant", "", "failed", tier, note=note
            )
            if isinstance(error, ApiError):
                raise
            raise gateway_error("unavailable", tier) from None
        return ChatResponse(
            browser_stream(
                stream,
                first,
                id,
                user_id,
                tier,
                note,
                history,
                tools,
                body.thinking,
                correlation,
            ),
            stream,
        )

    @app.get("/api/jobs")
    async def job_list(request: Request, claims: User) -> list[dict[str, Any]]:
        query(request, {"limit", "before"})
        try:
            page = Page.model_validate(dict(request.query_params))
        except ValueError:
            raise ApiError(400, "invalid_input", "Invalid pagination.") from None
        return await job_store.listing(claims["sub"], page.limit, page.before)

    @app.get("/api/jobs/{job_id}/file")
    async def file(request: Request, job_id: UUID, claims: User) -> FileResponse:
        query(request)
        job = await job_store.get(job_id, claims["sub"])
        path = download_path(settings.files_root, job)
        return FileResponse(path, media_type=job["output"]["mime"], filename=path.name)

    @app.get("/api/events")
    async def events(request: Request, claims: User) -> StreamingResponse:
        query(request)

        async def stream() -> AsyncGenerator[str]:
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
            subscribers = notifications.subscribers.setdefault(claims["sub"], set())
            subscribers.add(queue)
            try:
                while True:
                    remaining = float(claims["exp"]) - time.time()
                    if remaining <= 0:
                        return
                    try:
                        event = await asyncio.wait_for(
                            queue.get(), timeout=min(15, remaining)
                        )
                        if time.time() >= float(claims["exp"]):
                            return
                        yield data(event)
                    except TimeoutError:
                        if time.time() >= float(claims["exp"]):
                            return
                        yield ": keep-alive\n\n"
            finally:
                subscribers.discard(queue)
                if not subscribers:
                    notifications.subscribers.pop(claims["sub"], None)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/uploads")
    async def future(request: Request, claims: User) -> None:
        query(request)
        raise ApiError(503, "not_built_yet", "Uploads are not built yet.")

    return app


def factory() -> FastAPI:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return create_app(Settings.from_env())
