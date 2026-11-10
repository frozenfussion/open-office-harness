# SPDX-License-Identifier: AGPL-3.0-only
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
import psycopg
from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from gateway.config import Config
from gateway.database import Database
from gateway.engine import Engine
from gateway.identity import Identity
from gateway.models import Call, Classify, GatewayError
from gateway.registry import Registry


async def caller(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> dict[str, Any]:
    return await request.app.state.identity.authenticate(authorization)


def authorize_call(body: Call, claims: dict[str, Any]) -> bool:
    if claims.get("azp") == "ooh-harness-api":
        return False
    if (
        claims.get("azp") == "ooh-control-centre"
        and body.model_entry_id is not None
        and not body.stream
        and [message.model_dump() for message in body.messages]
        == [{"role": "user", "content": "Reply with the single word OK."}]
        and not body.tools
        and body.user_id.startswith("admin-test-")
    ):
        return True
    raise GatewayError(403, "forbidden", "This caller may not make this Gateway call")


def create_app(config: Config | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings = config or Config.environment()
        # HTTP library diagnostics include remote addresses; provider configuration is private.
        for name in ("httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.CRITICAL)
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=False, trust_env=False
        ) as client:
            app.state.db = Database(settings.db)
            app.state.identity = Identity(settings, client)
            app.state.engine = Engine(
                client, Registry(settings, client, app.state.identity), app.state.db
            )
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(GatewayError)
    async def gateway_error(request: Request, error: GatewayError) -> JSONResponse:
        body: dict[str, Any] = error.body()
        if getattr(request.state, "test_connection", False) and error.status == 503:
            body |= {
                "provider_status": error.provider_status,
                "provider_message": error.provider_message,
            }
        return JSONResponse(body, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {"code": "invalid_input", "message": "Invalid request"}, status_code=400
        )

    @app.exception_handler(psycopg.Error)
    async def database_error(request: Request, error: psycopg.Error) -> JSONResponse:
        return await gateway_error(
            request, GatewayError(503, "unavailable", "The database did not answer")
        )

    @app.get("/health")
    async def health(request: Request) -> dict[str, str]:
        await request.app.state.db.health()
        return {"status": "ok"}

    @app.post("/v1/call")
    async def call(
        body: Call, request: Request, claims: Annotated[dict[str, Any], Depends(caller)]
    ) -> Any:
        request.state.test_connection = authorize_call(body, claims)
        events = request.app.state.engine.events(
            body, provider_details=request.state.test_connection
        )
        try:
            first = await anext(events)
        except StopAsyncIteration:
            raise GatewayError(
                503, "unavailable", "The model did not answer. Try again."
            ) from None
        if body.stream:

            async def stream() -> AsyncIterator[str]:
                try:
                    yield "data: " + json.dumps(first) + "\n\n"
                    async for event in events:
                        yield "data: " + json.dumps(event) + "\n\n"
                except GatewayError, psycopg.Error:
                    yield 'data: {"type":"failed","error":{"code":"unavailable","message":"The model did not answer. Try again."}}\n\n'
                finally:
                    await events.aclose()

            return StreamingResponse(
                stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
            )
        content, tools, completed = "", [], None
        try:
            event = first
            while True:
                if event["type"] == "delta":
                    content += event["text"]
                elif event["type"] == "tool_call":
                    tools.append(
                        {key: value for key, value in event.items() if key != "type"}
                    )
                elif event["type"] == "completed":
                    completed = event
                elif event["type"] == "failed":
                    raise GatewayError(
                        503, "unavailable", "The model did not answer. Try again."
                    )
                try:
                    event = await anext(events)
                except StopAsyncIteration:
                    break
        finally:
            await events.aclose()
        if completed is None:
            raise GatewayError(
                503, "unavailable", "The model did not answer. Try again."
            )
        return {
            "content": content,
            "tool_calls": tools,
            **{key: value for key, value in completed.items() if key != "type"},
        }

    @app.post("/v1/classify")
    async def classify(
        body: Classify, claims: Annotated[dict[str, Any], Depends(caller)]
    ) -> JSONResponse:
        if claims.get("azp") != "ooh-harness-api":
            raise GatewayError(
                403, "forbidden", "Only the Harness service account may classify"
            )
        return JSONResponse(
            {"code": "not_built_yet", "message": "Classification arrives in Stage 3"},
            status_code=503,
        )

    return app
