# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Any
from uuid import UUID

import httpx
import psycopg
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BeforeValidator

from consumer.config import Config
from consumer.database import Database
from consumer.events import Bus, Processor, Runner
from consumer.identity import Identity
from consumer.identity_error import IdentityError


def day_input(value: Any) -> Any:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("day must be YYYY-MM-DD")
    return value


Day = Annotated[date, BeforeValidator(day_input)]


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
            app.state.identity = Identity(settings, client)
            bus = Bus(settings)
            app.state.db = Database(settings.db)
            handler = app.state.db
            processor = Processor(settings.name, bus, handler.handle)
            app.state.runner = Runner(bus, processor, ["audit.events"])
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

    @app.exception_handler(psycopg.Error)
    async def database_error(request: Request, error: psycopg.Error) -> JSONResponse:
        return JSONResponse(
            {"code": "unavailable", "message": "The database did not answer"},
            status_code=503,
        )

    @app.get("/health")
    async def health(request: Request) -> Any:
        await request.app.state.db.health()
        if not request.app.state.runner.healthy():
            return JSONResponse({"status": "down"}, status_code=503)
        return {"status": "ok"}

    @app.get("/v1/trail", dependencies=[Depends(caller)])
    async def trail(
        request: Request,
        correlation_id: UUID | None = None,
        user_id: Annotated[str | None, Query(min_length=1)] = None,
        actor: Annotated[str | None, Query(min_length=1)] = None,
        action: Annotated[str | None, Query(min_length=1)] = None,
        before_id: Annotated[int | None, Query(ge=1)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> Any:
        return await request.app.state.db.trail(
            {
                "correlation_id": correlation_id,
                "user_id": user_id,
                "actor": actor,
                "action": action,
            },
            before_id,
            limit,
        )

    @app.get("/v1/counts", dependencies=[Depends(caller)])
    async def counts(request: Request, day: Annotated[Day, Query()]) -> Any:
        return await request.app.state.db.counts(day)

    return app
