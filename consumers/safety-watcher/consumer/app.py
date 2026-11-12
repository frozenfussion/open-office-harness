# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from consumer.config import Config
from consumer.events import Bus, Processor, Runner
from consumer.identity import Identity
from consumer.identity_error import IdentityError
from consumer.safety import Safety
from consumer.tracing import instrument_app, instrument_client


async def caller(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> None:
    claims = await request.app.state.identity.authenticate(authorization)
    if claims.get("azp") != "ooh-control-centre":
        raise IdentityError(
            403,
            "forbidden",
            "Only the Control Centre service account may read this service",
        )


def create_app(config: Config | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings = config or Config.environment()
        for name in ("httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.CRITICAL)
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=False, trust_env=False
        ) as client:
            instrument_client(client)
            app.state.identity = Identity(settings, client)
            bus = Bus(settings)
            handler = Safety(settings, client, app.state.identity, bus)
            processor = Processor(settings.name, bus, handler.handle)
            app.state.runner = Runner(
                bus, processor, ["chat.messages", "skill.results"]
            )
            app.state.runner.task = asyncio.create_task(app.state.runner.run())
            try:
                yield
            finally:
                await app.state.runner.stop()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(IdentityError)
    async def identity_error(request: Request, error: IdentityError) -> JSONResponse:
        return JSONResponse(
            {"code": error.code, "message": error.message}, status_code=error.status
        )

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {"code": "invalid_input", "message": "Invalid request"}, status_code=400
        )

    @app.get("/health")
    async def health(request: Request) -> Any:

        if not request.app.state.runner.healthy():
            return JSONResponse({"status": "down"}, status_code=503)
        return {"status": "ok"}

    instrument_app(app)
    return app
