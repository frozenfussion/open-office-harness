# SPDX-License-Identifier: AGPL-3.0-only
import copy
import json
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import respx
from conftest import FakeDatabase, FakeRegistry
from test_http_identity_registry import token

from gateway.engine import Engine
from gateway.models import Call, Classify, Entry, GatewayError, Message

TYPES = ["openai_chat_completions", "anthropic_messages", "openai_responses"]
PATHS = {
    TYPES[0]: "/chat/completions",
    TYPES[1]: "/v1/messages",
    TYPES[2]: "/responses",
    "jev_systemone": "/v1/systemone",
}


def response(
    kind: str, tool: bool = False, text: str = "Final answer"
) -> dict[str, Any]:
    if kind == TYPES[0]:
        message: dict[str, Any] = {
            "content": text,
            "reasoning_content": "synthetic reasoning",
        }
        if tool:
            message["tool_calls"] = [
                {
                    "id": "fake-call",
                    "type": "function",
                    "function": {
                        "name": "fake_tool",
                        "arguments": '{"topic":"example"}',
                    },
                }
            ]
        return {
            "choices": [{"message": message}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 3},
        }
    if kind == TYPES[1]:
        blocks = [
            {
                "type": "thinking",
                "thinking": "synthetic reasoning",
                "signature": "synthetic-signature",
            },
            {"type": "redacted_thinking", "data": "synthetic-redacted"},
            {"type": "text", "text": text},
        ]
        if tool:
            blocks.append(
                {
                    "type": "tool_use",
                    "id": "fake-call",
                    "name": "fake_tool",
                    "input": {"topic": "example"},
                }
            )
        return {"content": blocks, "usage": {"input_tokens": 8, "output_tokens": 3}}
    items = [
        {
            "type": "reasoning",
            "id": "fake-reasoning",
            "summary": [],
            "encrypted_content": "synthetic-encrypted",
        },
        {
            "type": "message",
            "id": "fake-message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        },
    ]
    if tool:
        items.append(
            {
                "type": "function_call",
                "id": "fake-item",
                "call_id": "fake-call",
                "name": "fake_tool",
                "arguments": '{"topic":"example"}',
            }
        )
    return {"output": items, "usage": {"input_tokens": 8, "output_tokens": 3}}


def provider(kind: str, value: dict[str, Any], stream: bool) -> httpx.Response:
    if not stream:
        return httpx.Response(200, json=value)
    events = []
    if kind == TYPES[0]:
        message = copy.deepcopy(value["choices"][0]["message"])
        for index, tool in enumerate(message.get("tool_calls", [])):
            tool["index"] = index
        events = [
            {
                "choices": [{"delta": message, "finish_reason": "stop"}],
                "usage": value["usage"],
            },
            {"type": "done"},
        ]
    elif kind == TYPES[1]:
        events = [{"type": "message_start", "message": {"usage": {"input_tokens": 8}}}]
        for index, block in enumerate(value["content"]):
            block = copy.deepcopy(block)
            delta = None
            if block["type"] == "thinking":
                delta = {"type": "thinking_delta", "thinking": block["thinking"]}
                signature = block.pop("signature")
                block["thinking"] = ""
            elif block["type"] == "text":
                delta = {"type": "text_delta", "text": block["text"]}
                block["text"] = ""
            events.append(
                {"type": "content_block_start", "index": index, "content_block": block}
            )
            if delta:
                events.append(
                    {"type": "content_block_delta", "index": index, "delta": delta}
                )
            if block["type"] == "thinking":
                events.append(
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {"type": "signature_delta", "signature": signature},
                    }
                )
        events += [
            {"type": "message_delta", "usage": {"output_tokens": 3}},
            {"type": "message_stop"},
        ]
    else:
        for index, item in enumerate(value["output"]):
            if item["type"] == "message":
                events.append(
                    {
                        "type": "response.output_text.delta",
                        "delta": item["content"][0]["text"],
                    }
                )
            if item["type"] == "function_call":
                events.append(
                    {
                        "type": "response.output_item.added",
                        "output_index": index,
                        "item": item,
                    }
                )
            events.append(
                {
                    "type": "response.output_item.done",
                    "output_index": index,
                    "item": item,
                }
            )
        events.append({"type": "response.completed", "response": value})
    return httpx.Response(
        200, text="".join("data: " + json.dumps(e) + "\n\n" for e in events)
    )


@pytest.mark.anyio
@pytest.mark.parametrize("kind", TYPES)
@pytest.mark.parametrize("stream", [False, True])
async def test_tool_round_and_next_user_turn_replay_exact_state(
    entry: Entry, call: Call, kind: str, stream: bool
) -> None:
    entry = entry.model_copy(update={"api_type": kind})
    call = call.model_copy(update={"stream": stream, "tool_choice": "none"})
    first, final = response(kind, True), response(kind)
    with respx.mock as mock:
        route = mock.post(entry.endpoint_url + PATHS[kind]).mock(
            side_effect=[
                provider(kind, first, stream),
                provider(kind, final, stream),
                provider(kind, final, stream),
            ]
        )
        async with httpx.AsyncClient() as client:
            engine = Engine(client, FakeRegistry([entry]), FakeDatabase())
            events = [e async for e in engine.events(call)]
            completed = events[-1]
            state = completed["reasoning_state"]
            assert state["model_entry_id"] == str(entry.id)
            assistant = Message(
                role="assistant",
                content="Final answer",
                tool_calls=[
                    {
                        "id": "fake-call",
                        "name": "fake_tool",
                        "arguments": {"topic": "example"},
                    }
                ],
                reasoning_state=state,
            )
            history = [
                *call.messages,
                assistant,
                Message(
                    role="tool",
                    tool_call_id="fake-call",
                    content='{"job_id":"fake-job"}',
                ),
            ]
            follow = call.model_copy(
                update={"messages": history, "model_entry_id": entry.id}
            )
            second = [e async for e in engine.events(follow)]
            assert any(e.get("text") == "Final answer" for e in second)
            history += [
                Message(
                    role="assistant",
                    content="Final answer",
                    reasoning_state=second[-1]["reasoning_state"],
                ),
                Message(role="user", content="Another question"),
            ]
            third = [
                e
                async for e in engine.events(
                    call.model_copy(update={"messages": history})
                )
            ]
            assert third[-1]["reasoning_state"]["model_entry_id"] == str(entry.id)
        body = json.loads(route.calls[1].request.content)
        third_body = json.loads(route.calls[2].request.content)
        if kind == TYPES[0]:
            assert body["messages"][-2]["reasoning_content"] == "synthetic reasoning"
            assert body["messages"][-2]["tool_calls"][0]["type"] == "function"
            assert body["messages"][-1]["tool_call_id"] == "fake-call"
            assert (
                third_body["messages"][-2]["reasoning_content"] == "synthetic reasoning"
            )
            assert body["tool_choice"] == "none"
        elif kind == TYPES[1]:
            assert body["messages"][-2]["content"] == first["content"]
            assert (
                body["messages"][-1]["role"] == "user"
                and body["messages"][-1]["content"][0]["type"] == "tool_result"
            )
            assert third_body["messages"][-2]["content"] == final["content"]
            assert body["tool_choice"] == {"type": "none"}
        else:
            assert (
                body["store"] is False
                and "reasoning.encrypted_content" in body["include"]
            )
            assert body["input"][-4:-1] == first["output"]
            assert body["input"][-1] == {
                "type": "function_call_output",
                "call_id": "fake-call",
                "output": '{"job_id":"fake-job"}',
            }
            assert third_body["input"][-3:-1] == final["output"]
            assert body["tool_choice"] == "none"


@pytest.mark.anyio
@pytest.mark.parametrize("kind", TYPES)
async def test_nonmatching_history_state_dropped_not_error(
    entry: Entry, call: Call, kind: str
) -> None:
    entry = entry.model_copy(update={"api_type": kind})
    foreign = {
        "model_entry_id": str(uuid4()),
        "reasoning_content": "foreign-state",
        "content": [{"type": "text", "text": "foreign-state"}],
        "output": [{"type": "reasoning", "encrypted_content": "foreign-state"}],
    }
    history = [
        Message(role="assistant", content="Earlier answer", reasoning_state=foreign),
        *call.messages[1:],
    ]
    with respx.mock as mock:
        route = mock.post(entry.endpoint_url + PATHS[kind]).mock(
            return_value=provider(kind, response(kind), False)
        )
        async with httpx.AsyncClient() as client:
            events = [
                e
                async for e in Engine(
                    client, FakeRegistry([entry]), FakeDatabase()
                ).events(call.model_copy(update={"stream": False, "messages": history}))
            ]
        assert events[-1]["type"] == "completed"
        assert b"foreign-state" not in route.calls[0].request.content
        assert b"Earlier answer" in route.calls[0].request.content


@pytest.mark.anyio
@pytest.mark.parametrize("kind", TYPES)
@pytest.mark.parametrize("thinking", [False, True])
async def test_forced_tools_effective_thinking_choice(
    entry: Entry, call: Call, kind: str, thinking: bool
) -> None:
    from gateway.models import ToolChoice

    entry = entry.model_copy(
        update={
            "api_type": kind,
            "request_settings": {"thinking": {"type": "enabled"}},
            "request_settings_thinking_off": {"thinking": {"type": "disabled"}},
        }
    )
    with respx.mock as mock:
        route = mock.post(entry.endpoint_url + PATHS[kind]).mock(
            return_value=provider(kind, response(kind), False)
        )
        async with httpx.AsyncClient() as client:
            events = [
                e
                async for e in Engine(
                    client, FakeRegistry([entry]), FakeDatabase()
                ).events(
                    call.model_copy(
                        update={
                            "stream": False,
                            "thinking": thinking,
                            "tool_choice": ToolChoice(name="fake_tool"),
                        }
                    )
                )
            ]
        body = json.loads(route.calls[0].request.content)
    assert events[-1]["tool_choice_applied"] == (not thinking or kind == TYPES[2])
    assert (
        body["tool_choice"]
        == ({"type": "auto"} if thinking else {"type": "tool", "name": "fake_tool"})
        if kind == TYPES[1]
        else body["tool_choice"]
        == (
            "auto"
            if thinking
            else {"type": "function", "function": {"name": "fake_tool"}}
        )
        if kind == TYPES[0]
        else body["tool_choice"] == {"type": "function", "name": "fake_tool"}
    )


class Publisher:
    def __init__(self, fail: bool = False) -> None:
        self.rows: list[dict[str, Any]] = []
        self.fail = fail

    async def publish(self, value: dict[str, Any]) -> None:
        if self.fail:
            raise RuntimeError("fake Kafka failure")
        self.rows.append(value)


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["jev_systemone", *TYPES])
@pytest.mark.parametrize("bad", [None, "missing", "out_of_range", "bool"])
async def test_classification_scores_validation_and_failover(
    entry: Entry, kind: str, bad: str | None
) -> None:
    main = entry.model_copy(
        update={"purpose": "classification", "tier": None, "api_type": kind}
    )
    backup = main.model_copy(
        update={
            "id": UUID(int=2),
            "role": "backup",
            "endpoint_url": "https://backup.invalid",
        }
    )
    scores = {"risk": 0.8, "extra": 1}
    if bad == "missing":
        scores.pop("risk")
    elif bad == "out_of_range":
        scores["risk"] = 1.1
    elif bad == "bool":
        scores["risk"] = True

    def answer(scores: dict) -> dict:
        return (
            {
                "answers": {k: {"noul": v} for k, v in scores.items()},
                "usage": {"input_tokens": 8, "output_tokens": 3},
            }
            if kind == "jev_systemone"
            else response(kind, text=json.dumps(scores))
        )

    pub = Publisher()
    correlation = uuid4()
    with respx.mock as mock:
        route = mock.post(main.endpoint_url + PATHS[kind]).respond(
            200, json=answer(scores)
        )
        fallback = (
            mock.post(backup.endpoint_url + PATHS[kind]).respond(
                200, json=answer({"risk": 0.4})
            )
            if bad
            else None
        )
        async with httpx.AsyncClient() as client:
            engine = Engine(client, FakeRegistry([main, backup]), FakeDatabase(), pub)
            result = await engine.classify(
                Classify(
                    text="Synthetic example",
                    questions={"risk": "Is it risky?"},
                    user_id="fake-user",
                ),
                correlation,
            )
            await engine.drain_background()
        assert result["scores"] == {"risk": 0.4 if bad else 0.8}
        assert result["model_entry_id"] == str(backup.id if bad else main.id)
        if fallback:
            assert fallback.call_count == 1
        body = json.loads(route.calls[0].request.content)
        if kind == "jev_systemone":
            assert body == {
                "model": "fake-model",
                "state": "Synthetic example",
                "questions": {"risk": {"type": "noul", "instructions": "Is it risky?"}},
            }
        assert len(pub.rows) == 1 and pub.rows[0]["correlation_id"] == str(correlation)
        audit = pub.rows[0]["payload"]
        assert (
            audit["action"] == "model.classify" and audit["scores"] == result["scores"]
        )
        assert (
            audit["tokens"] == 11 and audit["cost_usd"] > 0 and audit["outcome"] == "ok"
        )
        assert "Synthetic example" not in json.dumps(pub.rows)


@pytest.mark.anyio
async def test_pinned_turn_no_failover_and_audit_failure_no_text(
    entry: Entry, call: Call
) -> None:
    pub, registry = (
        Publisher(),
        FakeRegistry(
            [entry, entry.model_copy(update={"id": UUID(int=2), "role": "backup"})]
        ),
    )
    reports = []

    async def report(entry: Entry, status: str, reason: str | None) -> None:
        reports.append((status, reason))

    registry.report_health = report
    with respx.mock as mock:
        route = mock.post(entry.endpoint_url + PATHS[entry.api_type]).respond(503)
        async with httpx.AsyncClient() as client:
            engine = Engine(client, registry, FakeDatabase(), pub)
            for _ in range(2):
                with pytest.raises(GatewayError) as error:
                    _ = [
                        e
                        async for e in engine.events(
                            call.model_copy(
                                update={"stream": False, "model_entry_id": entry.id}
                            )
                        )
                    ]
                assert error.value.code == "unavailable"
            route.respond(200, json=response(entry.api_type))
            _ = [
                e
                async for e in engine.events(call.model_copy(update={"stream": False}))
            ]
            _ = [
                e
                async for e in engine.events(call.model_copy(update={"stream": False}))
            ]
            await engine.drain_background()
        assert route.call_count == 4
    assert reports == [("down", "http_503"), ("ok", None)]
    assert [v["payload"]["outcome"] for v in pub.rows] == [
        "failed",
        "failed",
        "ok",
        "ok",
    ]
    assert pub.rows[0]["payload"]["model_entry_id"] == str(entry.id)
    assert "reasoning_state" not in json.dumps(
        pub.rows
    ) and "Example" not in json.dumps(pub.rows)


@pytest.mark.anyio
async def test_kafka_failure_does_not_fail_call(entry: Entry, call: Call) -> None:
    with respx.mock as mock:
        mock.post(entry.endpoint_url + PATHS[entry.api_type]).respond(
            200, json=response(entry.api_type)
        )
        async with httpx.AsyncClient() as client:
            events = [
                e
                async for e in Engine(
                    client, FakeRegistry([entry]), FakeDatabase(), Publisher(True)
                ).events(call.model_copy(update={"stream": False}))
            ]
        assert events[-1]["type"] == "completed"


@pytest.mark.parametrize(
    "azp,stream,pinned,status",
    [
        ("ooh-slides-worker", False, False, 200),
        ("ooh-slides-worker", True, False, 403),
        ("ooh-slides-worker", False, True, 403),
        ("ooh-safety-watcher", False, False, 403),
        ("ooh-harness-api", False, False, 200),
        ("ooh-workspace", False, False, 403),
    ],
)
def test_call_caller_rules(
    http: tuple, entry: Entry, azp: str, stream: bool, pinned: bool, status: int
) -> None:
    client, key = http
    body = {
        "purpose": "chat",
        "tier": 1,
        "user_id": "fake-user",
        "stream": stream,
        "messages": [{"role": "user", "content": "Example"}],
    }
    if pinned:
        body["model_entry_id"] = str(entry.id)
    with respx.mock as mock:
        if status == 200:
            mock.post(entry.endpoint_url + PATHS[entry.api_type]).respond(
                200, json=response(entry.api_type)
            )
        result = client.post(
            "/v1/call",
            json=body,
            headers={"Authorization": "Bearer " + token(key, azp=azp)},
        )
    assert result.status_code == status


@pytest.mark.parametrize(
    "azp,pinned,user,text,status",
    [
        ("ooh-harness-api", False, "fake-user", "Example", 200),
        ("ooh-safety-watcher", False, "fake-user", "Example", 200),
        ("ooh-slides-worker", False, "fake-user", "Example", 403),
        (
            "ooh-control-centre",
            True,
            "admin-test-fake-service",
            "This is a connection test.",
            200,
        ),
        (
            "ooh-control-centre",
            False,
            "admin-test-fake-service",
            "This is a connection test.",
            403,
        ),
        ("ooh-control-centre", True, "wrong-user", "This is a connection test.", 403),
        ("ooh-control-centre", True, "admin-test-fake-service", "Other text", 403),
    ],
)
def test_classify_caller_rules(
    http: tuple, entry: Entry, azp: str, pinned: bool, user: str, text: str, status: int
) -> None:
    client, key = http
    client.app.state.engine.registry = FakeRegistry(
        [
            entry.model_copy(
                update={
                    "purpose": "classification",
                    "tier": None,
                    "api_type": "jev_systemone",
                }
            )
        ]
    )
    body = {
        "text": text,
        "user_id": user,
        "questions": {"test": "Is this a connection test?"},
    }
    if pinned:
        body["model_entry_id"] = str(entry.id)
    with respx.mock as mock:
        if status == 200:
            mock.post(entry.endpoint_url + "/v1/systemone").respond(
                200, json={"answers": {"test": {"noul": 0.9}}}
            )
        result = client.post(
            "/v1/classify",
            json=body,
            headers={"Authorization": "Bearer " + token(key, azp=azp)},
        )
    assert result.status_code == status


@pytest.mark.parametrize(
    "change",
    [
        {"text": ""},
        {"text": "x" * 20001},
        {"questions": {}},
        {"questions": {"BAD": "question"}},
        {"questions": {"x": ""}},
        {"questions": {f"q{i}": "question" for i in range(11)}},
        {"model_entry_id": "bad"},
        {"extra": "bad"},
    ],
)
def test_classify_bad_input(http: tuple, change: dict) -> None:
    client, key = http
    result = client.post(
        "/v1/classify",
        json={
            "text": "Example",
            "user_id": "fake-user",
            "questions": {"x": "Question?"},
        }
        | change,
        headers={"Authorization": "Bearer " + token(key)},
    )
    assert result.status_code == 400
