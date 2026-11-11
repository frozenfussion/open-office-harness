# SPDX-License-Identifier: AGPL-3.0-only
import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

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
        "UPDATE messages SET thinking='changed' WHERE id=%s",
        "DELETE FROM messages WHERE id=%s",
        "TRUNCATE messages",
        "DELETE FROM conversations WHERE id=%s",
        "TRUNCATE conversations CASCADE",
        "DELETE FROM jobs",
        "TRUNCATE jobs",
        "UPDATE processed_events SET topic=topic",
        "DELETE FROM processed_events",
        "TRUNCATE processed_events",
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
def db_user() -> str:
    return "stage-check-" + str(uuid4())


@pytest.fixture
async def store(
    db_settings: tuple[str, str], monkeypatch: pytest.MonkeyPatch, db_user: str
) -> AsyncIterator[Store]:
    original_connect = psycopg.AsyncConnection.connect
    db = await original_connect(db_settings[1], row_factory=psycopg.rows.dict_row)
    try:
        await db.execute("BEGIN")
        try:
            with monkeypatch.context() as patch:

                async def connect(*args: Any, **kwargs: Any) -> Borrowed:
                    return Borrowed(db)

                patch.setattr(psycopg.AsyncConnection, "connect", connect)
                yield Store(db_settings[1])
        finally:
            await db.rollback()
    finally:
        await db.close()
    async with await original_connect(db_settings[1]) as observer:
        cursor = await observer.execute(
            "SELECT (SELECT count(*) FROM conversations WHERE user_id=%s), "
            "(SELECT count(*) FROM messages WHERE created_by=%s)",
            (db_user, db_user),
        )
        assert await cursor.fetchone() == (0, 0), "Storage test rows escaped rollback"


@pytest.mark.anyio
async def test_store_ownership_history_and_metadata(store: Store, db_user: str) -> None:
    user = db_user
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
async def test_history_starts_at_user(store: Store, db_user: str) -> None:
    user = db_user
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


@pytest.mark.anyio
async def test_title_source_and_update_preserve_ownership_and_order(
    store: Store, db_user: str
) -> None:
    identifier = await store.create(db_user)
    await store.append(identifier, db_user, "user", "First question", "completed", 3)
    failed = await store.append(
        identifier, db_user, "assistant", "Partial", "failed", 3
    )
    tool = await store.append(
        identifier, db_user, "assistant", "Tool", "tool_requested", 3
    )
    await store.append(identifier, db_user, "user", "Next question", "completed", 1)
    first = await store.append(
        identifier, db_user, "assistant", "First answer", "completed", 1
    )
    assert await store.title_source(identifier, db_user, failed) is None
    assert await store.title_source(identifier, db_user, tool) is None
    assert await store.title_source(identifier, "other-user", first) is None
    assert await store.title_source(identifier, db_user, first) == {
        "question": "First question",
        "answer": "First answer",
    }
    before = (await store.listing(db_user, 20, None))[0]["updated_at"]
    assert not await store.set_title(
        identifier, "other-user", "Wrong title", "First question"
    )
    assert await store.set_title(
        identifier, db_user, "A useful short title", "First question"
    )
    assert (await store.listing(db_user, 20, None))[0]["updated_at"] == before
    assert await store.title_source(identifier, db_user, first) is None
    assert not await store.set_title(identifier, db_user, "Overwrite", "First question")
    row = await store.conversation(identifier, db_user)
    assert row["title"] == "A useful short title"
    assert len(row["messages"]) == 5
    later = await store.append(
        identifier, db_user, "assistant", "Later answer", "completed", 1
    )
    assert await store.title_source(identifier, db_user, later) is None
    other = await store.create(db_user)
    assert await store.title_source(other, db_user, first) is None


@pytest.mark.anyio
async def test_thinking_is_inserted_and_read_but_not_used_as_model_context(
    store: Store, db_user: str
) -> None:
    identifier = await store.create(db_user)
    await store.append(identifier, db_user, "user", "Question", "completed", 1)
    first = await store.append(
        identifier,
        db_user,
        "assistant",
        "Answer",
        "completed",
        1,
        thinking="PRIVATE_DATABASE_THINKING",
    )
    await store.append(
        identifier,
        db_user,
        "assistant",
        "Partial",
        "failed",
        1,
        thinking="PARTIAL_DATABASE_THINKING",
    )
    row = await store.conversation(identifier, db_user)
    assert row["messages"][0]["thinking"] is None
    assert row["messages"][1]["thinking"] == "PRIVATE_DATABASE_THINKING"
    assert row["messages"][2]["thinking"] == "PARTIAL_DATABASE_THINKING"
    assert row["messages"][2]["outcome"] == "failed"
    assert await store.history(identifier) == [
        {"role": "user", "content": "Question"},
        {"role": "assistant", "content": "Answer"},
    ]
    assert await store.title_source(identifier, db_user, first) == {
        "question": "Question",
        "answer": "Answer",
    }


@pytest.mark.anyio
@pytest.mark.parametrize("outcome", ["completed", "failed", "tool_requested"])
async def test_database_thinking_is_bounded_for_every_outcome(
    store: Store, db_user: str, outcome: str
) -> None:
    identifier = await store.create(db_user)
    await store.append(identifier, db_user, "user", "Question", "completed", 1)
    await store.append(
        identifier, db_user, "assistant", "Answer", outcome, 1, thinking="思" * 100_001
    )
    row = await store.conversation(identifier, db_user)
    assert row["messages"][-1]["thinking"] == "思" * 100_000
    assert row["messages"][-1]["outcome"] == outcome


@pytest.mark.anyio
async def test_private_reasoning_round_trip(store: Store, db_user: str) -> None:
    identifier = await store.create(db_user)
    await store.append(identifier, db_user, "user", "Question", "completed", 1)
    state = {"model_entry_id": str(uuid4()), "opaque": "PRIVATE_REASONING"}
    await store.append(
        identifier,
        db_user,
        "assistant",
        "Answer",
        "completed",
        1,
        {"reasoning_state": state, "model_entry_id": state["model_entry_id"]},
    )
    assert (await store.history(identifier))[-1]["reasoning_state"] == state
    assert (
        "reasoning_state"
        not in (await store.conversation(identifier, db_user))["messages"][-1]
    )


@pytest.mark.anyio
@pytest.mark.parametrize("decision", ["approved", "rejected", "removed", "unavailable"])
async def test_jobs_approval_results_and_protections(
    store: Store,
    db_user: str,
    h: Any,
    decision: str,
) -> None:
    from harness_api.errors import ApiError
    from harness_api.events import JobEvents, envelope
    from harness_api.jobs import Jobs

    notifications = JobEvents()
    jobs = Jobs(store.connection, h.app.state.upstream, h.publisher, notifications)
    identifier = await store.create(db_user)
    h.skills.respond(
        json=[
            {
                "name": "slides",
                "title": "Example skill",
                "description": "Example tool",
                "input_schema": "contracts/skills/slides/input.schema.json",
                "needs_approval": True,
                "topic": "skill.requests.slides",
                "version": "1.0.0",
            }
        ]
    )
    result, card = await jobs.start(
        db_user, identifier, {"name": "slides", "arguments": {"topic": "Example"}}
    )
    job_id = result["job_id"]
    assert card["status"] == "awaiting_approval" and card["label"] == "Example"
    assert [
        event[1]["payload"]["action"]
        for event in h.publisher.events
        if event[0] == "audit.events"
    ] == ["rights.check", "skill.awaiting_approval"]
    if decision == "removed":
        h.rights.respond(json={"chat_tiers": [1], "skills": []})
    elif decision == "unavailable":
        h.rights.respond(503)
    event = envelope(
        "approval.decided",
        job_id,
        db_user,
        {"approved": decision != "rejected", "decided_by": "test-admin", "note": ""},
    )
    await jobs.handle("approvals.decided", event)
    row = await jobs.get(UUID(job_id), db_user)
    expected = {
        "approved": "queued",
        "rejected": "rejected",
        "removed": "failed",
        "unavailable": "failed",
    }[decision]
    assert row["status"] == expected
    published = len(h.publisher.events)
    await jobs.handle("approvals.decided", event)
    assert len(h.publisher.events) == published
    if decision == "approved":
        output = {
            "file_key": "outputs/slides/example.pptx",
            "mime": "application/octet-stream",
            "summary": "Example",
        }
        completed = envelope(
            "skill.result",
            job_id,
            db_user,
            {"skill": "slides", "status": "completed", "output": output, "error": None},
        )
        await jobs.handle("skill.results", completed)
        await jobs.handle("skill.results", completed)
        failed = envelope(
            "skill.result",
            job_id,
            db_user,
            {
                "skill": "slides",
                "status": "failed",
                "output": None,
                "error": {"code": "example", "message": "Example"},
            },
        )
        await jobs.handle("skill.results", failed)
        assert (await jobs.get(UUID(job_id), db_user))["output"] == output
    with pytest.raises(ApiError):
        await jobs.get(UUID(job_id), "other-user")
    with pytest.raises(ApiError):
        await jobs.listing("other-user", 20, UUID(job_id))
    assert [row["job_id"] for row in await jobs.listing(db_user, 1, None)] == [job_id]
    assert await jobs.listing(db_user, 20, UUID(job_id)) == []
    await jobs.handle(
        "skill.results",
        envelope(
            "skill.result",
            str(uuid4()),
            db_user,
            {
                "skill": "slides",
                "status": "failed",
                "output": None,
                "error": {"code": "example", "message": "Example"},
            },
        ),
    )
    async with await psycopg.AsyncConnection.connect(store.connection) as db:
        for statement in (
            "DELETE FROM jobs",
            "TRUNCATE jobs",
            "UPDATE processed_events SET topic=topic",
            "DELETE FROM processed_events",
            "TRUNCATE processed_events",
        ):
            with pytest.raises(psycopg.Error):
                async with db.transaction():
                    await db.execute(statement)


@pytest.mark.anyio
async def test_jobs_refusal_queue_failure_and_paging(
    store: Store, db_user: str, h: Any
) -> None:
    from harness_api.events import JobEvents
    from harness_api.jobs import Jobs

    jobs = Jobs(store.connection, h.app.state.upstream, h.publisher, JobEvents())
    conversation = await store.create(db_user)
    for tool in (
        {"name": "other", "arguments": {}},
        {"name": "slides", "arguments": {}},
    ):
        result, event = await jobs.start(db_user, conversation, tool)
        assert "error" in result and event is None
    h.publisher.fail = True
    result, event = await jobs.start(
        db_user, conversation, {"name": "slides", "arguments": {"topic": "Example"}}
    )
    assert result == {"error": "The job could not be started."}
    assert event["status"] == "failed"
    assert (await jobs.listing(db_user, 20, None))[0]["error"][
        "code"
    ] == "queue_unavailable"


@pytest.mark.anyio
@pytest.mark.parametrize("failed_audit", ["rights.check", "skill.requested"])
async def test_audit_failure_keeps_queued_job_completable(
    store: Store,
    db_user: str,
    h: Any,
    failed_audit: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from harness_api.events import JobEvents, envelope
    from harness_api.jobs import Jobs

    published = []

    async def publish(topic: str, event: dict[str, Any]) -> None:
        if topic == "audit.events" and event["payload"]["action"] == failed_audit:
            raise RuntimeError("synthetic audit outage")
        published.append((topic, event))

    monkeypatch.setattr(h.publisher, "publish", publish)
    jobs = Jobs(store.connection, h.app.state.upstream, h.publisher, JobEvents())
    conversation = await store.create(db_user)
    result, card = await jobs.start(
        db_user, conversation, {"name": "slides", "arguments": {"topic": "Example"}}
    )
    assert result["status"] == card["status"] == "queued"
    assert any(topic == "skill.requests.slides" for topic, _ in published)
    output = {
        "file_key": "outputs/slides/example.pptx",
        "mime": "application/octet-stream",
        "summary": "Example",
    }
    await jobs.handle(
        "skill.results",
        envelope(
            "skill.result",
            result["job_id"],
            db_user,
            {"skill": "slides", "status": "completed", "output": output, "error": None},
        ),
    )
    assert (await jobs.get(UUID(result["job_id"]), db_user))["status"] == "completed"
    assert any(
        getattr(record, "code", "") == "audit_publish_failed"
        for record in caplog.records
    )
