# SPDX-License-Identifier: AGPL-3.0-only
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


async def migrate(connection: str) -> None:
    async with await psycopg.AsyncConnection.connect(connection) as db:
        await db.execute("SELECT pg_advisory_xact_lock(643002)")
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
        values = [
            event[k]
            for k in (
                "event_id",
                "occurred_at",
                "user_id",
                "producer",
                "correlation_id",
            )
        ]
        values += [payload[k] for k in ("actor", "action", "target", "outcome")]
        values += [payload.get(k) for k in ("model", "tokens", "cost_usd")]
        values.append(Jsonb(payload["scores"]) if "scores" in payload else None)
        values.append(payload.get("trace_id"))
        try:
            async with await psycopg.AsyncConnection.connect(self.connection) as db:
                await db.execute(
                    "INSERT INTO trail(event_id,occurred_at,user_id,producer,correlation_id,actor,action,target,outcome,model,tokens,cost_usd,scores,trace_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (event_id) DO NOTHING",
                    values,
                )
        except psycopg.Error:
            raise RuntimeError("database_failed") from None

    async def trail(
        self, filters: dict[str, Any], before_id: int | None, limit: int
    ) -> list[dict[str, Any]]:
        clauses, values = [], []
        for key in ("correlation_id", "user_id", "actor", "action", "trace_id"):
            if filters.get(key) is not None:
                clauses.append(key + " = %s")
                values.append(filters[key])
        if before_id is not None:
            clauses.append(
                "(occurred_at,id) < (SELECT occurred_at,id FROM trail WHERE id = %s)"
            )
            values.append(before_id)
        where = " AND ".join(clauses) if clauses else "true"
        async with await psycopg.AsyncConnection.connect(
            self.connection, row_factory=dict_row
        ) as db:
            return await (
                await db.execute(
                    "SELECT * FROM trail WHERE "
                    + where
                    + " ORDER BY occurred_at DESC, id DESC LIMIT %s",
                    (*values, limit),
                )
            ).fetchall()

    async def counts(
        self, day: date, *, bounds: tuple[datetime, datetime] | None = None
    ) -> dict[str, Any]:
        selected_bounds = bounds if bounds is not None else window(day)
        async with await psycopg.AsyncConnection.connect(
            self.connection, row_factory=dict_row
        ) as db:
            rows = await (
                await db.execute(
                    "SELECT action,count(*) AS n FROM trail WHERE occurred_at >= %s AND occurred_at < %s GROUP BY action",
                    selected_bounds,
                )
            ).fetchall()
            distinct = await (
                await db.execute(
                    "SELECT count(DISTINCT user_id) AS n FROM trail WHERE occurred_at >= %s AND occurred_at < %s AND user_id <> 'system' AND NOT starts_with(user_id,'title-') AND NOT starts_with(user_id,'admin-test-') AND NOT starts_with(user_id,'stage-check-') AND NOT starts_with(user_id,'service-account-')",
                    selected_bounds,
                )
            ).fetchone()
            return {
                "day": day.isoformat(),
                "by_action": {r["action"]: r["n"] for r in rows},
                "distinct_users": distinct["n"],
            }
