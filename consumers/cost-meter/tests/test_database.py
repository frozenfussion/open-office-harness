# SPDX-License-Identifier: AGPL-3.0-only
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from test_events import event

from consumer.database import Database, migrate


@dataclass
class Connections:
    owner: str = field(repr=False)
    app: str = field(repr=False)


@pytest.fixture
def connections() -> Connections:
    owner = os.environ.get("CM_TEST_DB_MIGRATE_CONNECTION")
    app = os.environ.get("CM_TEST_DB_CONNECTION")
    if not owner or not app:
        pytest.skip(
            "run install/74-consumers-setup.sh and load the private test settings"
        )
    for value in (owner, app):
        if conninfo_to_dict(value).get("dbname") != "costmeter_test":
            pytest.fail("database tests require costmeter_test")
    return Connections(owner, app)


class Borrowed:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    async def __aenter__(self) -> Any:
        return self.connection

    async def __aexit__(self, *args: object) -> None:
        pass


@pytest.mark.anyio
async def test_migration_repeat_append_only_owner_and_app_rolled_back(
    connections: Connections,
) -> None:
    await migrate(connections.owner)
    await migrate(connections.owner)
    for connection in (connections.owner, connections.app):
        async with (
            await psycopg.AsyncConnection.connect(connection) as db,
            db.transaction(force_rollback=True),
        ):
            value = event()
            row = await (
                await db.execute(
                    "INSERT INTO model_costs(event_id,occurred_at,user_id,action,model,model_entry_id,tokens,cost_usd) VALUES (%s,%s,%s,'model.call','Fake entry','fake-entry',5,0.01) RETURNING id",
                    (value["event_id"], value["occurred_at"], value["user_id"]),
                )
            ).fetchone()
            for statement in (
                "UPDATE model_costs SET tokens=9 WHERE id=%s",
                "DELETE FROM model_costs WHERE id=%s",
                "TRUNCATE model_costs",
            ):
                with pytest.raises(psycopg.Error):
                    async with db.transaction():
                        await db.execute(
                            statement, (row[0],) if "%s" in statement else None
                        )
            assert (
                await (
                    await db.execute(
                        "SELECT tokens FROM model_costs WHERE id=%s", (row[0],)
                    )
                ).fetchone()
            )[0] == 5


@pytest.mark.anyio
async def test_insert_idempotency_filters_and_utc_aggregates(
    connections: Connections, monkeypatch: pytest.MonkeyPatch
) -> None:
    await migrate(connections.owner)
    connect = psycopg.AsyncConnection.connect
    async with (
        await connect(connections.app, row_factory=psycopg.rows.dict_row) as db,
        db.transaction(force_rollback=True),
    ):

        async def borrowed(*args: Any, **kwargs: Any) -> Borrowed:
            return Borrowed(db)

        monkeypatch.setattr(psycopg.AsyncConnection, "connect", borrowed)
        store = Database(connections.app)
        value = event()
        value["occurred_at"] = "2099-03-04T23:59:59Z"
        await store.handle("audit.events", value)
        await store.handle("audit.events", value)
        assert (
            await (
                await db.execute(
                    "SELECT count(*) AS n FROM model_costs WHERE event_id=%s",
                    (value["event_id"],),
                )
            ).fetchone()
        )["n"] == 1
        result = await store.costs(date(2099, 3, 4))
        assert (
            result["calls"] == 1
            and result["tokens"] == 5
            and float(result["total_usd"]) == 0.01
        )
        assert result["by_model"][0]["model"] == "Fake entry"
        next_day = event()
        next_day["occurred_at"] = "2099-03-05T00:00:00Z"
        next_day["payload"]["action"] = "model.classify"
        await store.handle("audit.events", next_day)
        assert (await store.costs(date(2099, 3, 4)))["calls"] == 1
        assert (await store.costs(date(2099, 3, 5)))["calls"] == 1
        skipped = event()
        skipped["occurred_at"] = value["occurred_at"]
        skipped["payload"]["action"] = "rights.check"
        await store.handle("audit.events", skipped)
        assert (await store.costs(date(2099, 3, 4)))["calls"] == 1
