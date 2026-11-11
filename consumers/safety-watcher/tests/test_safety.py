# SPDX-License-Identifier: AGPL-3.0-only
import json
from typing import Any

import httpx
import pytest
import respx
from test_events import Bus, event

from consumer.config import Config
from consumer.events import SCHEMA, Processor
from consumer.safety import Safety

CONFIG = Config(
    questions={"risk": "Is there a risk?"},
    gateway_url="https://gateway.invalid",
    threshold=0.8,
)


class Identity:
    async def service_token(self) -> str:
        return "synthetic-token"


def chat() -> dict:
    value = event()
    value["type"] = "chat.message"
    value["payload"] = {
        "conversation_id": value["correlation_id"],
        "message_id": value["event_id"],
        "role": "user",
        "text": "Synthetic text for the safety test.",
        "tier": 1,
        "model_title": None,
    }
    return value


@pytest.mark.anyio
@pytest.mark.parametrize(
    "score,outcome,rows", [(0.79, "clear", 1), (0.8, "flagged", 2), (1, "flagged", 2)]
)
async def test_threshold_excerpt_and_stable_outgoing_ids(
    score: float, outcome: str, rows: int
) -> None:
    value, bus = chat(), Bus()
    SCHEMA.validate(value)
    with respx.mock as mock:
        route = mock.post(CONFIG.gateway_url + "/v1/classify").respond(
            200, json={"scores": {"risk": score}}
        )
        async with httpx.AsyncClient() as client:
            handler = Safety(CONFIG, client, Identity(), bus)
            await handler.handle("chat.messages", value)
            await handler.handle("chat.messages", value)
        request = route.calls[0].request
        assert request.headers["X-Correlation-Id"] == value["correlation_id"]
        assert json.loads(request.content)["user_id"] == value["user_id"]
    assert len(bus.rows) == rows * 2
    assert bus.rows[0][1]["payload"]["outcome"] == outcome
    assert bus.rows[0][1]["event_id"] == bus.rows[rows][1]["event_id"]
    assert value["payload"]["text"] not in json.dumps(bus.rows[0])
    if rows == 2:
        flag = bus.rows[1][1]
        assert flag["payload"]["details"]["excerpt"] == value["payload"]["text"][:300]
        assert flag["event_id"] == bus.rows[3][1]["event_id"]
        assert flag["correlation_id"] == value["correlation_id"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status,code,outcome",
    [
        (404, "no_model", "skipped_no_classifier"),
        (429, "rate_limited", "skipped_rate_limited"),
        (503, "unavailable", "skipped_unavailable"),
        (503, "budget_exceeded", "skipped_unavailable"),
        (503, "registry_unavailable", "skipped_unavailable"),
    ],
)
async def test_expected_unavailable_has_audit_no_retry_no_dlq(
    status: int, code: str, outcome: str
) -> None:
    bus = Bus()
    with respx.mock as mock:
        route = mock.post(CONFIG.gateway_url + "/v1/classify").respond(
            status, json={"code": code}
        )
        async with httpx.AsyncClient() as client:
            handler = Safety(CONFIG, client, Identity(), bus)
            processor = Processor(CONFIG.name, bus, handler.handle)
            await processor.process("chat.messages", json.dumps(chat()).encode())
        assert route.call_count == 1
    assert len(bus.rows) == 1
    assert (
        bus.rows[0][0] == "audit.events"
        and bus.rows[0][1]["payload"]["outcome"] == outcome
    )


@pytest.mark.anyio
@pytest.mark.parametrize("bad_payload", [False, True])
async def test_chat_text_never_in_dlq(bad_payload: bool) -> None:
    value, bus, waits = chat(), Bus(), []
    value["payload"]["text"] = "synthetic-private-text"
    if bad_payload:
        value["payload"]["unexpected"] = "synthetic-private-text"

    async def broken(*args: Any) -> None:
        raise RuntimeError("synthetic-private-text")

    async def sleep(seconds: int) -> None:
        waits.append(seconds)

    processor = Processor(CONFIG.name, bus, broken, sleep)
    await processor.process("chat.messages", json.dumps(value).encode())
    assert len(bus.rows) == 1 and bus.rows[0][0] == "dlq.chat.messages"
    assert "synthetic-private-text" not in json.dumps(bus.rows)
    original = json.loads(bus.rows[0][1]["payload"]["original_message"])
    assert set(original) == {"event_id", "correlation_id", "message_id"}
    assert waits == ([] if bad_payload else [1, 5, 15])


@pytest.mark.anyio
async def test_failed_skill_skipped_completed_summary_classified() -> None:
    value, bus = event(), Bus()
    value["type"] = "skill.result"
    value["payload"] = {
        "skill": "slides",
        "status": "failed",
        "output": None,
        "error": {"code": "fake", "message": "fake"},
    }
    with respx.mock as mock:
        route = mock.post(CONFIG.gateway_url + "/v1/classify").respond(
            200, json={"scores": {"risk": 0}}
        )
        async with httpx.AsyncClient() as client:
            handler = Safety(CONFIG, client, Identity(), bus)
            await handler.handle("skill.results", value)
            assert route.call_count == 0
            value["payload"] = {
                "skill": "slides",
                "status": "completed",
                "output": {
                    "file_key": "outputs/slides/fake.pptx",
                    "mime": "fake",
                    "summary": "Synthetic summary",
                },
                "error": None,
            }
            await handler.handle("skill.results", value)
        assert json.loads(route.calls[0].request.content)["text"] == "Synthetic summary"
    assert len(bus.rows) == 1
