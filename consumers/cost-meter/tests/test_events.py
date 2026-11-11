# SPDX-License-Identifier: AGPL-3.0-only
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from consumer.events import SCHEMA, Processor, outgoing


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def event() -> dict[str, Any]:
    return {
        "event_id": str(uuid4()),
        "type": "audit.event",
        "version": 1,
        "occurred_at": "2026-11-11T00:00:00Z",
        "correlation_id": str(uuid4()),
        "user_id": "fake-user",
        "producer": "fake-producer",
        "payload": {
            "actor": "fake-user",
            "action": "model.call",
            "target": "chat:1",
            "outcome": "ok",
            "model": "Fake entry",
            "model_entry_id": str(uuid4()),
            "tokens": 5,
            "cost_usd": 0.01,
        },
    }


class Bus:
    def __init__(self) -> None:
        self.rows: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, topic: str, value: dict[str, Any]) -> None:
        SCHEMA.validate(value)
        self.rows.append((topic, value))


@pytest.mark.anyio
@pytest.mark.parametrize(
    "bad", [b"not json", b"[]", b"{}", b'"text"', b"\xff", b"", b"null", b"1"]
)
async def test_invalid_envelope_dlq_without_retry(bad: bytes) -> None:
    bus = Bus()

    async def forbidden(*args: Any) -> None:
        pytest.fail("invalid message must never reach handler or wait")

    processor = Processor("cost-meter", bus, forbidden, forbidden)
    await processor.process("audit.events", bad)
    assert len(bus.rows) == 1 and bus.rows[0][0] == "dlq.audit.events"
    value = bus.rows[0][1]
    assert (
        value["user_id"] == "system"
        and value["payload"]["error"]["code"] == "invalid_message"
    )


@pytest.mark.anyio
@pytest.mark.parametrize("mutation", ["payload", "type", "time", "id"])
async def test_invalid_payload_or_envelope_dlq_immediately(mutation: str) -> None:
    value = event()
    if mutation == "payload":
        value["payload"]["cost_usd"] = -1
    elif mutation == "type":
        value["type"] = "skill.result"
    elif mutation == "time":
        value["occurred_at"] = "yesterday"
    else:
        value["event_id"] = "bad"
    bus = Bus()

    async def forbidden(*args: Any) -> None:
        pytest.fail("invalid message must never reach handler or wait")

    await Processor("cost-meter", bus, forbidden, forbidden).process(
        "audit.events", json.dumps(value).encode()
    )
    assert bus.rows[0][0] == "dlq.audit.events"
    assert bus.rows[0][1]["correlation_id"] == value["correlation_id"]
    assert bus.rows[0][1]["user_id"] == value["user_id"]


@pytest.mark.anyio
async def test_retry_schedule_then_dlq_and_successful_duplicate_ignored() -> None:
    bus, attempts, waits = Bus(), [], []

    async def broken(topic: str, value: dict) -> None:
        attempts.append(value["event_id"])
        raise RuntimeError("fake failure")

    async def sleep(seconds: int) -> None:
        waits.append(seconds)

    value = event()
    raw = json.dumps(value).encode()
    await Processor("cost-meter", bus, broken, sleep).process("audit.events", raw)
    assert len(attempts) == 4 and waits == [1, 5, 15]
    assert len(bus.rows) == 1 and bus.rows[0][0] == "dlq.audit.events"
    handled = []

    async def good(topic: str, value: dict) -> None:
        handled.append(value["event_id"])

    processor = Processor("cost-meter", bus, good)
    await processor.process("audit.events", raw)
    await processor.process("audit.events", raw)
    assert handled == [value["event_id"]]


def test_outgoing_event_ids_stable_and_schema_copies_equal_contract() -> None:
    value = event()
    payload = value["payload"]
    first = outgoing(value, "cost-meter", "audit.event", payload)
    assert (
        first["event_id"]
        == outgoing(value, "cost-meter", "audit.event", payload)["event_id"]
    )
    assert (
        first["event_id"]
        != outgoing(event(), "cost-meter", "audit.event", payload)["event_id"]
    )
    SCHEMA.validate(first)
    root = Path(__file__).resolve().parents[3]
    copies = Path(__file__).resolve().parents[1] / "consumer/schemas"
    for path in copies.rglob("*.json"):
        assert json.loads(path.read_text()) == json.loads(
            (root / "contracts/events" / path.relative_to(copies)).read_text()
        )


@pytest.mark.anyio
@pytest.mark.parametrize("action", ["model.call", "model.classify"])
@pytest.mark.parametrize(
    "missing", [("model",), ("model_entry_id",), ("model", "model_entry_id")]
)
async def test_no_entry_cost_event_skipped_and_counted_handled(
    action: str, missing: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    import psycopg

    from consumer.database import Database

    async def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("an event without an entry must not touch the database or retry")

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", forbidden)
    value = event()
    value["payload"].update(action=action, outcome="failed", tokens=0, cost_usd=0)
    for key in missing:
        value["payload"].pop(key)
    bus = Bus()
    processor = Processor("cost-meter", bus, Database("unused").handle, forbidden)
    raw = json.dumps(value).encode()
    await processor.process("audit.events", raw)
    assert value["event_id"] in processor.seen
    await processor.process("audit.events", raw)
    assert bus.rows == []
