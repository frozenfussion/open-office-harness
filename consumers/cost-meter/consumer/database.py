# SPDX-License-Identifier: AGPL-3.0-only
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


async def migrate(connection: str) -> None:
    async with await psycopg.AsyncConnection.connect(connection) as db:
        await db.execute("SELECT pg_advisory_xact_lock(643003)")
        await db.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        rows = await (
            await db.execute("SELECT version FROM schema_migrations")
        ).fetchall()
        applied = {row[0] for row in rows}
        for path in sorted(
            (Path(__file__).resolve().parents[1] / "migrations").glob("*.sql")
        ):
            if path.name not in applied:
                await db.execute(path.read_text(), prepare=False)
                await db.execute(
                    "INSERT INTO schema_migrations(version) VALUES (%s)", (path.name,)
                )
        app_role = (
            await (await db.execute("SELECT current_database() || '_app'")).fetchone()
        )[0]
        await db.execute(
            sql.SQL("REVOKE ALL ON schema_migrations FROM {}, PUBLIC").format(
                sql.Identifier(app_role)
            )
        )


def window(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, datetime.min.time(), UTC)
    return start, start + timedelta(days=1)


class Database:
    def __init__(self, connection: str) -> None:
        self.connection = connection

    async def health(self) -> None:
        async with await psycopg.AsyncConnection.connect(self.connection) as db:
            await db.execute("SELECT 1")

    async def handle(self, topic: str, event: dict[str, Any]) -> None:
        payload = event["payload"]
        if payload["action"] not in {"model.call", "model.classify"}:
            return
        if "model" not in payload or "model_entry_id" not in payload:
            return
        values = [event[k] for k in ("event_id", "occurred_at", "user_id")]
        values += [
            payload[k]
            for k in ("action", "model", "model_entry_id", "tokens", "cost_usd")
        ]
        try:
            async with await psycopg.AsyncConnection.connect(self.connection) as db:
                await db.execute(
                    "INSERT INTO model_costs(event_id,occurred_at,user_id,action,model,model_entry_id,tokens,cost_usd) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (event_id) DO NOTHING",
                    values,
                )
        except psycopg.Error:
            raise RuntimeError("database_failed") from None

    async def costs(
        self, day: date, *, bounds: tuple[datetime, datetime] | None = None
    ) -> dict[str, Any]:
        selected_bounds = bounds if bounds is not None else window(day)
        async with await psycopg.AsyncConnection.connect(
            self.connection, row_factory=dict_row
        ) as db:
            total = await (
                await db.execute(
                    "SELECT coalesce(sum(cost_usd),0) AS total_usd,count(*) AS calls,coalesce(sum(tokens),0) AS tokens FROM model_costs WHERE occurred_at >= %s AND occurred_at < %s",
                    selected_bounds,
                )
            ).fetchone()
            rows = await (
                await db.execute(
                    "SELECT model,count(*) AS calls,sum(tokens) AS tokens,sum(cost_usd) AS cost_usd FROM model_costs WHERE occurred_at >= %s AND occurred_at < %s GROUP BY model ORDER BY model",
                    selected_bounds,
                )
            ).fetchall()
            return {"day": day.isoformat(), **total, "by_model": rows}
