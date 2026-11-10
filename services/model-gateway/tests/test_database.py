# SPDX-License-Identifier: AGPL-3.0-only
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from gateway.database import Database, migrate
from gateway.models import Call, Entry


@dataclass
class PrivateConnections:
    owner: str = field(repr=False)
    app: str = field(repr=False)

    def __iter__(self) -> Iterator[str]:
        yield self.owner
        yield self.app


@pytest.fixture
def connections() -> PrivateConnections:
    owner = os.environ.get("GW_TEST_DB_MIGRATE_CONNECTION")
    app = os.environ.get("GW_TEST_DB_CONNECTION")
    if not owner or not app:
        pytest.skip(
            "run install/64-model-gateway-setup.sh and load the private test settings"
        )
    for value in (owner, app):
        if conninfo_to_dict(value).get("dbname") != "modelgateway_test":
            pytest.fail("database tests require modelgateway_test")
    return PrivateConnections(owner, app)


@pytest.mark.anyio
async def test_migration_repeat_and_append_only(
    connections: PrivateConnections, entry: Entry, call: Call
) -> None:
    owner, app = connections
    await migrate(owner)
    await migrate(owner)
    for connection in connections:
        async with (
            await psycopg.AsyncConnection.connect(connection) as db,
            db.transaction(force_rollback=True),
        ):
            row_id = (
                await (
                    await db.execute(
                        "INSERT INTO usage(model_entry_id,user_id,purpose,tier,outcome,input_tokens,output_tokens,cost_usd,duration_ms) VALUES (%s,'fake-user','chat',1,'ok',1,2,0.1,3) RETURNING id",
                        (uuid4(),),
                    )
                ).fetchone()
            )[0]
            for statement in (
                "UPDATE usage SET input_tokens=7 WHERE id=%s",
                "DELETE FROM usage WHERE id=%s",
                "TRUNCATE usage",
            ):
                with pytest.raises(psycopg.Error):
                    async with db.transaction():
                        await db.execute(
                            statement, (row_id,) if "%s" in statement else None
                        )
            assert (
                await (
                    await db.execute(
                        "SELECT input_tokens FROM usage WHERE id=%s", (row_id,)
                    )
                ).fetchone()
            )[0] == 1
    db = Database(app)
    await db.health()
    assert await db.limits(entry.model_copy(update={"id": uuid4()}), call) == (
        0,
        Decimal(0),
    )


@pytest.mark.anyio
async def test_usage_record_rate_window_and_utc_budget(
    connections: PrivateConnections,
    entry: Entry,
    call: Call,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await migrate(connections.owner)
    entry = entry.model_copy(update={"id": uuid4()})
    async with (
        await psycopg.AsyncConnection.connect(connections.app) as connection,
        connection.transaction(force_rollback=True),
    ):
        await connection.execute("SET LOCAL TIME ZONE 'Pacific/Auckland'")

        class Borrowed:
            async def __aenter__(self) -> psycopg.AsyncConnection:
                return connection

            async def __aexit__(self, *args: object) -> None:
                return None

        async def borrow(*args: object, **kwargs: object) -> Borrowed:
            return Borrowed()

        monkeypatch.setattr(psycopg.AsyncConnection, "connect", borrow)
        database = Database(connections.app)
        await database.record(entry, call, "ok", 8, 3, Decimal("0.003"), 12)
        await database.record(entry, call, "failed", 0, 0, Decimal("0.002"), 10)
        await database.record(entry, call, "skipped_rate", 0, 0, Decimal(0), 0)
        await database.record(entry, call, "skipped_budget", 0, 0, Decimal(0), 0)
        await database.record(
            entry,
            call.model_copy(update={"user_id": "other-fake-user"}),
            "ok",
            1,
            1,
            Decimal("0.004"),
            2,
        )
        await connection.execute(
            "INSERT INTO usage(occurred_at,model_entry_id,user_id,purpose,tier,outcome,input_tokens,output_tokens,cost_usd,duration_ms) VALUES (date_trunc('day',now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' - interval '1 second',%s,'historical-fake-user','chat',1,'ok',1,1,100,2)",
            (entry.id,),
        )
        assert await database.limits(entry, call) == (2, Decimal("0.009000"))
        assert await database.limits(
            entry.model_copy(update={"id": uuid4()}), call
        ) == (0, Decimal(0))
