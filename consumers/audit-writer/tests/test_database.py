# SPDX-License-Identifier: AGPL-3.0-only
import os
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

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
    owner = os.environ.get("AW_TEST_DB_MIGRATE_CONNECTION")
    app = os.environ.get("AW_TEST_DB_CONNECTION")
    if not owner or not app:
        pytest.skip(
            "run install/74-consumers-setup.sh and load the private test settings"
        )
    for value in (owner, app):
        if conninfo_to_dict(value).get("dbname") != "auditwriter_test":
            pytest.fail("database tests require auditwriter_test")
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
                    "INSERT INTO trail(event_id,occurred_at,user_id,producer,correlation_id,actor,action,target,outcome,model,tokens,cost_usd) VALUES (%s,%s,%s,%s,%s,'fake','model.call','chat:1','ok','Fake entry',5,0.01) RETURNING id",
                    (
                        value["event_id"],
                        value["occurred_at"],
                        value["user_id"],
                        value["producer"],
                        value["correlation_id"],
                    ),
                )
            ).fetchone()
            for statement in (
                "UPDATE trail SET tokens=9 WHERE id=%s",
                "DELETE FROM trail WHERE id=%s",
                "TRUNCATE trail",
            ):
                with pytest.raises(psycopg.Error):
                    async with db.transaction():
                        await db.execute(
                            statement, (row[0],) if "%s" in statement else None
                        )
            assert (
                await (
                    await db.execute("SELECT tokens FROM trail WHERE id=%s", (row[0],))
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
                    "SELECT count(*) AS n FROM trail WHERE event_id=%s",
                    (value["event_id"],),
                )
            ).fetchone()
        )["n"] == 1
        rows = await store.trail({"correlation_id": value["correlation_id"]}, None, 50)
        assert len(rows) == 1 and rows[0]["user_id"] == value["user_id"]
        assert await store.trail({"correlation_id": str(uuid4())}, None, 50) == []
        newer = event()
        newer["occurred_at"] = "2099-03-05T00:00:00Z"
        await store.handle("audit.events", newer)
        before = await store.counts(date(2099, 3, 4))
        assert before["by_action"]["model.call"] == 1 and before["distinct_users"] == 1
        for user in [
            "title-fake",
            "admin-test-fake",
            "stage-check-fake",
            "service-account-fake",
            "system",
            "another-user",
            "fake-user",
        ]:
            item = event()
            item["occurred_at"] = value["occurred_at"]
            item["user_id"] = user
            await store.handle("audit.events", item)
        result = await store.counts(date(2099, 3, 4))
        assert result["distinct_users"] == 2 and result["by_action"]["model.call"] == 8
        assert (await store.counts(date(2099, 3, 5)))["by_action"]["model.call"] == 1
        page1 = await store.trail(
            {"action": "model.call", "actor": "fake-user"}, None, 1
        )
        page2 = await store.trail(
            {"action": "model.call", "actor": "fake-user"}, page1[0]["id"], 20
        )
        assert page1[0]["id"] not in {r["id"] for r in page2}
        assert len(page2) == 8


@pytest.mark.anyio
async def test_summary_range_is_half_open_and_crosses_utc_midnight(
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
        start = datetime(2099, 5, 10, 16, tzinfo=UTC)
        end = start + timedelta(days=1)
        for index, instant in enumerate(
            [start - timedelta(microseconds=1), start, start + timedelta(hours=12), end]
        ):
            value = event()
            value["occurred_at"] = instant.isoformat().replace("+00:00", "Z")
            value["user_id"] = f"fake-window-person-{index}"
            await store.handle("audit.events", value)
        result = await store.counts(start.date(), bounds=(start, end))
        assert result["day"] == "2099-05-10"
        assert result["by_action"] == {"model.call": 2}
        assert result["distinct_users"] == 2
