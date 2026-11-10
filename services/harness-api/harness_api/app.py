# SPDX-License-Identifier: AGPL-3.0-only
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import UUID

import anyio
import httpx
import psycopg
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from starlette.exceptions import HTTPException
from starlette.types import Receive, Scope, Send

from .auth import Auth
from .config import Settings
from .errors import ApiError, gateway_error
from .store import Store
from .upstream import GatewayStream, Upstream


class Empty(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Message(Empty):
    content: str = Field(min_length=1)
    tier: Annotated[StrictInt, Field(gt=0)] | None = None

    @field_validator("content")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Content must not be blank")
        return value


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
) -> FastAPI:
    http = client or httpx.AsyncClient(timeout=10, follow_redirects=False)
    database = store or Store(settings.database)
    auth = Auth(settings, http)
    upstream = Upstream(settings, http, auth)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        if client is None:
            await http.aclose()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.auth = auth
    app.state.upstream = upstream
    app.state.store = database

    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(error.body(), status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {"code": "invalid_input", "message": "Invalid input."}, status_code=400
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
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
        tiers, skills = await upstream.permissions(claims["sub"])
        name = claims.get("name", "")
        return {
            "user_id": claims["sub"],
            "name": name if isinstance(name, str) else "",
            "chat_tiers": tiers,
            "skills": [{"name": skill.name, "title": skill.title} for skill in skills],
        }

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

    async def browser_stream(
        stream: GatewayStream,
        first: dict[str, Any],
        identifier: UUID,
        user_id: str,
        tier: int,
        titles: dict[str, str],
        note: str | None,
    ) -> AsyncGenerator[str]:
        content = ""
        outcome = "failed"
        metadata: dict[str, Any] = {}
        saved = False
        tool_requested = False
        try:
            event = first
            while True:
                match event["type"]:
                    case "delta":
                        if not tool_requested:
                            content += event["text"]
                            yield data(event)
                    case "tool_call":
                        if event["name"] not in titles:
                            raise ValueError("Unapproved tool")
                        if not tool_requested:
                            sentence = (
                                f"I would use the {titles[event['name']]} "
                                "skill for this. "
                                "Skills are switched on in the next stage."
                            )
                            content += sentence
                            tool_requested = True
                            yield data({"type": "delta", "text": sentence})
                    case "completed":
                        metadata = event
                        outcome = "tool_requested" if tool_requested else "completed"
                        message_id = await database.append(
                            identifier,
                            user_id,
                            "assistant",
                            content,
                            outcome,
                            tier,
                            metadata,
                            note,
                        )
                        saved = True
                        yield data(
                            {
                                "type": "completed",
                                "message_id": str(message_id),
                                "tier": tier,
                                "model_title": event["model_title"],
                                "usage": event["usage"],
                                "note": note,
                            }
                        )
                        return
                    case "failed":
                        raise gateway_error(event["error"]["code"], tier)
                event = await anext(stream.events)
        except (
            ApiError,
            httpx.HTTPError,
            ValueError,
            KeyError,
            TypeError,
            StopAsyncIteration,
        ) as error:
            failure = (
                error
                if isinstance(error, ApiError)
                else gateway_error("unavailable", tier)
            )
            yield data({"type": "failed", "error": failure.body()})
        finally:
            # A browser disconnect cancels the generator; keep its partial answer.
            with anyio.CancelScope(shield=True):
                try:
                    await stream.close()
                finally:
                    if not saved:
                        await database.append(
                            identifier,
                            user_id,
                            "assistant",
                            content,
                            "failed",
                            tier,
                            metadata,
                            note,
                        )

    @app.post("/api/conversations/{id}/messages")
    async def send(
        request: Request, id: UUID, body: Message, claims: User
    ) -> StreamingResponse:
        query(request)
        user_id = claims["sub"]
        await database.conversation(id, user_id)
        tiers, skills = await upstream.permissions(user_id)
        if body.tier is None and not tiers:
            raise ApiError(
                403, "no_tier", "You have no chat tier yet. An admin can grant one."
            )
        tier = body.tier if body.tier is not None else tiers[0]
        await upstream.check(user_id, tier)
        tools = upstream.tools(skills)
        titles = {
            skill.name: skill.title
            for skill in skills
            if skill.name in upstream.schemas
        }
        history = await database.history(id)
        history.append({"role": "user", "content": body.content})
        await database.append(id, user_id, "user", body.content, "completed", tier)
        note = None
        stream = None
        try:
            try:
                stream = await upstream.open(user_id, tier, history, tools)
            except ApiError as error:
                lower = [value for value in tiers if value < tier]
                if error.code != "budget_exceeded" or not lower:
                    raise
                original = tier
                tier = lower[0]
                await upstream.check(user_id, tier)
                note = (
                    f"tier {original} is over its daily budget; "
                    f"answered with tier {tier}"
                )
                stream = await upstream.open(user_id, tier, history, tools)
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
            browser_stream(stream, first, id, user_id, tier, titles, note), stream
        )

    @app.post("/api/uploads")
    @app.get("/api/events")
    @app.get("/api/files/{key}")
    async def future(request: Request, claims: User, key: str | None = None) -> None:
        query(request)
        raise ApiError(503, "not_built_yet", "Files and job events arrive in Stage 3.")

    return app


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Never include exception strings or third-party request details.
        return json.dumps(
            {
                "level": record.levelname.lower(),
                "event": "service_log",
                "logger": record.name,
            }
        )


def factory() -> FastAPI:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return create_app(Settings.from_env())
