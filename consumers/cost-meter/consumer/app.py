# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

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
from consumer.tracing import instrument_app


def cost_number(value: Decimal | float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.000001")))


def day_input(value: Any) -> Any:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("day must be YYYY-MM-DD")
    return value


Day = Annotated[date, BeforeValidator(day_input)]


def utc_input(value: Any) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("timestamp must be ISO 8601 UTC")
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None or instant.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return instant.astimezone(UTC)


UtcInstant = Annotated[datetime, BeforeValidator(utc_input)]


def summary_window(
    day: date | None, start: datetime | None, end: datetime | None
) -> tuple[date, tuple[datetime, datetime] | None]:
    if start is not None or end is not None:
        if (
            start is None
            or end is None
            or not timedelta(0) < end - start <= timedelta(days=31)
        ):
            raise ValueError(
                "from and to require an ordered UTC range of at most 31 days"
            )
        return start.date(), (start, end)
    if day is None:
        raise ValueError("day or from and to is required")
    return day, None


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

    @app.get("/v1/costs", dependencies=[Depends(caller)])
    async def costs(
        request: Request,
        day: Annotated[Day | None, Query()] = None,
        from_: Annotated[UtcInstant | None, Query(alias="from")] = None,
        to: Annotated[UtcInstant | None, Query()] = None,
    ) -> Any:
        try:
            selected_day, bounds = summary_window(day, from_, to)
        except ValueError:
            return JSONResponse(
                {"code": "invalid_input", "message": "Invalid date range"},
                status_code=400,
            )
        result = (
            await request.app.state.db.costs(selected_day)
            if bounds is None
            else await request.app.state.db.costs(selected_day, bounds=bounds)
        )
        result["total_usd"] = cost_number(result["total_usd"])
        for row in result["by_model"]:
            row["cost_usd"] = cost_number(row["cost_usd"])
        return result

    instrument_app(app)
    return app
