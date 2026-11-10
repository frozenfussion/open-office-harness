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
    claims = await request.app.state.identity.authenticate(authorization)
    if claims.get("azp") != "ooh-harness-api":
        raise GatewayError(
            403, "forbidden", "Only the Harness service account may call the Gateway"
        )
    return claims


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
        return JSONResponse(error.body(), status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {"code": "invalid_input", "message": "Invalid request"}, status_code=400
        )

    @app.exception_handler(psycopg.Error)
    async def database_error(request: Request, error: psycopg.Error) -> JSONResponse:
        return JSONResponse(
            {"code": "unavailable", "message": "The database did not answer"},
            status_code=503,
        )

    @app.get("/health")
    async def health(request: Request) -> dict[str, str]:
        await request.app.state.db.health()
        return {"status": "ok"}

    @app.post("/v1/call", dependencies=[Depends(caller)])
    async def call(body: Call, request: Request) -> Any:
        events = request.app.state.engine.events(body)
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

    @app.post("/v1/classify", dependencies=[Depends(caller)])
    async def classify(body: Classify) -> JSONResponse:
        return JSONResponse(
            {"code": "not_built_yet", "message": "Classification arrives in Stage 3"},
            status_code=503,
        )

    return app
