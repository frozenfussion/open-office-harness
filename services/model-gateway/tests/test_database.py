# SPDX-License-Identifier: AGPL-3.0-only
import os
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from gateway.database import Database, migrate
from gateway.models import Call, Entry


@pytest.fixture
def connections() -> tuple[str, str]:
    owner = os.environ.get("GW_TEST_DB_MIGRATE_CONNECTION")
    app = os.environ.get("GW_TEST_DB_CONNECTION")
    if not owner or not app:
        pytest.skip(
            "run install/64-model-gateway-setup.sh and load the private test settings"
        )
    for value in (owner, app):
        if conninfo_to_dict(value).get("dbname") != "modelgateway_test":
            pytest.fail("database tests require modelgateway_test")
    return owner, app


@pytest.mark.anyio
async def test_migration_repeat_and_append_only(
    connections: tuple[str, str], entry: Entry, call: Call
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
