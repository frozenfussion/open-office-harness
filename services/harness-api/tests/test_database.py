# SPDX-License-Identifier: AGPL-3.0-only
import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from harness_api.migrate import migrate
from harness_api.store import Store


def connections() -> tuple[str, str]:
    owner = os.environ.get("HA_TEST_DB_MIGRATE_CONNECTION")
    app = os.environ.get("HA_TEST_DB_CONNECTION")
    if not owner or not app:
        pytest.skip(
            "Database setup has not been confirmed; load the private test settings"
        )
    for connection, role in ((owner, "harness_test"), (app, "harness_test_app")):
        parsed = conninfo_to_dict(connection)
        if parsed.get("dbname") != "harness_test" or parsed.get("user") != role:
            pytest.fail("Refusing a connection outside the Harness test database")
    return owner, app


@pytest.fixture(scope="module")
def db_settings() -> tuple[str, str]:
    owner, app = connections()
    try:
        migrate(owner)
        migrate(owner)
    except Exception:
        pytest.fail(
            "Test database migration failed; inspect database readiness privately"
        )
    return owner, app


@pytest.mark.parametrize("role", [0, 1], ids=["owner", "app"])
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE messages SET content='changed' WHERE id=%s",
        "DELETE FROM messages WHERE id=%s",
        "TRUNCATE messages",
        "DELETE FROM conversations WHERE id=%s",
        "TRUNCATE conversations CASCADE",
        "UPDATE schema_migrations SET name=name",
        "DELETE FROM schema_migrations",
        "TRUNCATE schema_migrations",
    ],
)
def test_database_protections(
    db_settings: tuple[str, str], role: int, statement: str
) -> None:
    with psycopg.connect(db_settings[role]) as db:
        with db.transaction(force_rollback=True):
            conversation = uuid4()
            message = uuid4()
            db.execute(
                "INSERT INTO conversations(id,user_id,title,created_at,updated_at,"
                "created_by,updated_by) VALUES (%s,'test-user','Example',"
                "now(),now(),'test-user','test-user')",
                (conversation,),
            )
            db.execute(
                "INSERT INTO messages(id,conversation_id,role,content,outcome,"
                "created_at,created_by) VALUES (%s,%s,'user','Example',"
                "'completed',now(),'test-user')",
                (message, conversation),
            )
            with pytest.raises(psycopg.Error), db.transaction():
                db.execute(
                    statement,
                    (message if "messages" in statement else conversation,)
                    if "%s" in statement
                    else None,
                )
            assert db.execute(
                "SELECT content FROM messages WHERE id=%s", (message,)
            ).fetchone() == ("Example",)


class Borrowed:
    def __init__(self, db: psycopg.AsyncConnection[Any]) -> None:
        self.db = db

    async def __aenter__(self) -> psycopg.AsyncConnection[Any]:
        return self.db

    async def __aexit__(self, *args: Any) -> None:
        return None


@pytest.fixture
async def store(
    db_settings: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Store]:
    db = await psycopg.AsyncConnection.connect(
        db_settings[1], row_factory=psycopg.rows.dict_row
    )
    async with db:
        async with db.transaction(force_rollback=True):

            async def connect(*args: Any, **kwargs: Any) -> Borrowed:
                return Borrowed(db)

            monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
            yield Store(db_settings[1])


@pytest.mark.anyio
async def test_store_ownership_history_and_metadata(store: Store) -> None:
    user = "stage-check-" + str(uuid4())
    identifier = await store.create(user)
    newer = await store.create(user)
    assert [row["id"] for row in await store.listing(user, 1, None)] == [newer]
    assert [row["id"] for row in await store.listing(user, 20, newer)] == [identifier]
    assert await store.listing("other-user", 20, None) == []
    from harness_api.errors import ApiError

    with pytest.raises(ApiError):
        await store.conversation(identifier, "other-user")
    with pytest.raises(ApiError):
        await store.listing("other-user", 20, identifier)
    assert await store.history(identifier) == []
    # Insert enough records to cut a pair in half at the window boundary.
    await store.append(identifier, user, "user", "First " * 20, "completed", 2)
    for index in range(11):
        await store.append(
            identifier, user, "user", f"Question {index}", "completed", 2
        )
        await store.append(
            identifier, user, "assistant", f"Answer {index}", "completed", 2
        )
    await store.append(identifier, user, "assistant", "Partial", "failed", 2)
    await store.append(identifier, user, "assistant", "Tool", "tool_requested", 2)
    await store.append(identifier, user, "assistant", "", "completed", 2)
    history = await store.history(identifier)
    assert len(history) == 20
    assert history[0] == {"role": "user", "content": "Question 1"}
    assert history[-1] == {"role": "assistant", "content": "Answer 10"}
    row = await store.conversation(identifier, user)
    assert row["title"] == ("First " * 20)[:60]
    assert len(row["messages"]) == 26
    assert row["messages"][-2]["outcome"] == "tool_requested"
    metadata = {
        "model_entry_id": str(uuid4()),
        "model_title": "Example model",
        "usage": {"input_tokens": 9, "output_tokens": 4},
    }
    message = await store.append(
        identifier,
        user,
        "assistant",
        "Complete",
        "completed",
        1,
        metadata,
        "Example note",
    )
    row = await store.conversation(identifier, user)
    last = row["messages"][-1]
    assert last["id"] == message
    assert last["model_title"] == "Example model"
    assert last["input_tokens"] == 9 and last["output_tokens"] == 4
    assert last["note"] == "Example note" and last["tier"] == 1
    await store.health()


@pytest.mark.anyio
async def test_history_starts_at_user(store: Store) -> None:
    user = "stage-check-" + str(uuid4())
    identifier = await store.create(user)
    await store.append(identifier, user, "user", "Old question", "completed", 1)
    await store.append(
        identifier, user, "assistant", "Orphan at boundary", "completed", 1
    )
    for index in range(9):
        await store.append(
            identifier, user, "user", f"Question {index}", "completed", 1
        )
        await store.append(
            identifier, user, "assistant", f"Answer {index}", "completed", 1
        )
    await store.append(identifier, user, "user", "Newest question", "completed", 1)
    history = await store.history(identifier)
    assert len(history) == 19
    assert history[0] == {"role": "user", "content": "Question 0"}
    assert history[-1] == {"role": "user", "content": "Newest question"}
