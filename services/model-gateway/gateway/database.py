# SPDX-License-Identifier: AGPL-3.0-only
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg import sql

from gateway.models import Call, Entry


async def migrate(connection: str) -> None:
    async with await psycopg.AsyncConnection.connect(connection) as db:
        await db.execute("SELECT pg_advisory_xact_lock(642001)")
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


class Database:
    def __init__(self, connection: str) -> None:
        self.connection = connection

    async def health(self) -> None:
        async with await psycopg.AsyncConnection.connect(self.connection) as db:
            await db.execute("SELECT 1")

    async def limits(self, entry: Entry, call: Call) -> tuple[int, Decimal]:
        async with await psycopg.AsyncConnection.connect(self.connection) as db:
            row = await (
                await db.execute(
                    """
                SELECT count(*) FILTER (WHERE user_id = %s AND occurred_at >= now() - interval '60 seconds' AND outcome IN ('ok','failed')),
                       coalesce(sum(cost_usd) FILTER (WHERE occurred_at >= date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'), 0)
                FROM usage WHERE model_entry_id = %s AND occurred_at >= least(now() - interval '60 seconds', date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')
            """,
                    (call.user_id, entry.id),
                )
            ).fetchone()
            return row[0], row[1]

    async def record(
        self,
        entry: Entry,
        call: Call,
        outcome: str,
        input_tokens: int,
        output_tokens: int,
        cost: Decimal,
        duration_ms: int,
    ) -> None:
        async with await psycopg.AsyncConnection.connect(self.connection) as db:
            await db.execute(
                "INSERT INTO usage(model_entry_id,user_id,purpose,tier,outcome,input_tokens,output_tokens,cost_usd,duration_ms) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    entry.id,
                    call.user_id,
                    call.purpose,
                    call.tier,
                    outcome,
                    input_tokens,
                    output_tokens,
                    cost,
                    duration_ms,
                ),
            )
