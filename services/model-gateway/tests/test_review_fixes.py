# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
import json
from typing import Any
from uuid import UUID

import httpx
import pytest
import respx
from conftest import FakeDatabase, FakeRegistry
from test_http_identity_registry import token
from test_stage3 import PATHS, TYPES, provider, response

from gateway.adapters import resolve
from gateway.app import create_app
from gateway.engine import Engine
from gateway.models import Call, Entry, GatewayError, ToolChoice


@pytest.mark.anyio
@pytest.mark.parametrize("kind", TYPES)
@pytest.mark.parametrize(
    "thinking",
    [
        None,
        {},
        {"type": "enabled"},
        {"type": "adaptive"},
        {"type": "disabled"},
        {"type": "disabled", "extra": True},
    ],
)
async def test_thinking_rule_applies_only_to_explicit_chat_or_messages_settings(
    entry: Entry, call: Call, kind: str, thinking: Any
) -> None:
    entry = entry.model_copy(
        update={
            "api_type": kind,
            "request_settings": {} if thinking is None else {"thinking": thinking},
        }
    )
    forced = call.model_copy(
        update={"stream": False, "tool_choice": ToolChoice(name="fake_tool")}
    )
    with respx.mock as mock:
        route = mock.post(entry.endpoint_url + PATHS[kind]).mock(
            return_value=provider(kind, response(kind), False)
        )
        async with httpx.AsyncClient() as client:
            events = [
                e async for e in resolve(entry)(client, entry, "synthetic-key", forced)
            ]
        body = json.loads(route.calls[0].request.content)
    applied = next(e["applied"] for e in events if e["type"] == "tool_choice_applied")
    assert applied == (
        kind == "openai_responses"
        or thinking is None
        or thinking == {"type": "disabled"}
    )
    if not applied:
        assert body["tool_choice"] == ({"type": "auto"} if kind == TYPES[1] else "auto")


@pytest.mark.anyio
@pytest.mark.parametrize("kind", TYPES)
@pytest.mark.parametrize("stream", [False, True])
async def test_forced_400_retries_auto_once_same_pinned_entry_no_down_health(
    entry: Entry, call: Call, kind: str, stream: bool
) -> None:
    entry = entry.model_copy(
        update={
            "api_type": kind,
            "request_settings": {"thinking": {"type": "disabled"}},
        }
    )
    registry, db, reports = (
        FakeRegistry(
            [
                entry,
                entry.model_copy(
                    update={
                        "id": UUID(int=2),
                        "role": "backup",
                        "endpoint_url": "https://backup.invalid",
                    }
                ),
            ]
        ),
        FakeDatabase(),
        [],
    )

    async def health(entry: Entry, status: str, reason: str | None) -> None:
        reports.append((status, reason))

    registry.report_health = health
    with respx.mock as mock:
        route = mock.post(entry.endpoint_url + PATHS[kind]).mock(
            side_effect=[httpx.Response(400), provider(kind, response(kind), stream)]
        )
        async with httpx.AsyncClient() as client:
            engine = Engine(client, registry, db)
            events = [
                e
                async for e in engine.events(
                    call.model_copy(
                        update={
                            "stream": stream,
                            "model_entry_id": entry.id,
                            "tool_choice": ToolChoice(name="fake_tool"),
                        }
                    )
                )
            ]
            await engine.drain_background()
        assert route.call_count == 2 and len(mock.calls) == 2
        first, second = [json.loads(c.request.content) for c in route.calls]
    assert first["tool_choice"] not in ("auto", {"type": "auto"})
    assert second["tool_choice"] == ({"type": "auto"} if kind == TYPES[1] else "auto")
    assert (
        events[-1]["type"] == "completed" and events[-1]["tool_choice_applied"] is False
    )
    assert events[-1]["model_entry_id"] == str(entry.id)
    assert reports == [("ok", None)]
    assert len(db.rows) == 1 and db.rows[0][2] == "ok"


@pytest.mark.anyio
async def test_400_retry_is_bounded(entry: Entry, call: Call) -> None:
    entry = entry.model_copy(
        update={"request_settings": {"thinking": {"type": "disabled"}}}
    )
    with respx.mock as mock:
        route = mock.post(entry.endpoint_url + PATHS[entry.api_type]).respond(400)
        async with httpx.AsyncClient() as client:
            engine = Engine(client, FakeRegistry([entry]), FakeDatabase())
            with pytest.raises(GatewayError):
                _ = [
                    e
                    async for e in engine.events(
                        call.model_copy(
                            update={
                                "stream": False,
                                "model_entry_id": entry.id,
                                "tool_choice": ToolChoice(name="fake_tool"),
                            }
                        )
                    )
                ]
            await engine.drain_background()
        assert route.call_count == 2


@pytest.mark.anyio
async def test_400_after_output_never_retries(entry: Entry, call: Call) -> None:
    entry = entry.model_copy(
        update={"request_settings": {"thinking": {"type": "disabled"}}}
    )

    async def adapter(*args: Any, **kwargs: Any) -> Any:
        from gateway.adapters.common import ProviderError

        yield {"type": "delta", "text": "Started answer"}
        raise ProviderError(400)

    from gateway.adapters import ADAPTERS

    original = ADAPTERS[entry.api_type]
    ADAPTERS[entry.api_type] = adapter
    try:
        async with httpx.AsyncClient() as client:
            engine = Engine(client, FakeRegistry([entry]), FakeDatabase())
            events = [
                e
                async for e in engine.events(
                    call.model_copy(
                        update={
                            "stream": True,
                            "tool_choice": ToolChoice(name="fake_tool"),
                        }
                    )
                )
            ]
            await engine.drain_background()
        assert [e["type"] for e in events] == ["delta", "failed"]
    finally:
        ADAPTERS[entry.api_type] = original


def test_classification_connection_test_uses_admin_subject_not_service_subject(
    http: tuple, entry: Entry
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
    with respx.mock as mock:
        mock.post(entry.endpoint_url + "/v1/systemone").respond(
            200, json={"answers": {"test": {"noul": 0.9}}}
        )
        result = client.post(
            "/v1/classify",
            json={
                "text": "This is a connection test.",
                "questions": {"test": "Is this a connection test?"},
                "model_entry_id": str(entry.id),
                "user_id": "admin-test-different-admin",
            },
            headers={
                "Authorization": "Bearer "
                + token(key, azp="ooh-control-centre", sub="different-service-account")
            },
        )
    assert result.status_code == 200 and result.json()["scores"] == {"test": 0.9}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "route,stream,failed",
    [
        ("/v1/call", False, False),
        ("/v1/call", True, False),
        ("/v1/classify", False, False),
        ("/v1/call", False, True),
    ],
)
async def test_slow_side_effects_start_after_response_and_timeout_without_delay(
    entry: Entry,
    call: Call,
    route: str,
    stream: bool,
    failed: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sent = []
    started = {"health": asyncio.Event(), "audit": asyncio.Event()}
    cancelled = []

    async def wait(kind: str) -> None:
        assert any(
            m["type"] == "http.response.body" and not m.get("more_body", False)
            for m in sent
        )
        started[kind].set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(kind)

    class Publisher:
        async def publish(self, value: dict) -> None:
            await wait("audit")

    async def health(*args: Any) -> None:
        await wait("health")

    class Identity:
        async def authenticate(self, authorization: str | None) -> dict:
            return {"azp": "ooh-harness-api", "sub": "fake-service"}

    selected = (
        entry.model_copy(update={"purpose": "classification", "tier": None})
        if route == "/v1/classify"
        else entry
    )
    registry = FakeRegistry([selected])
    registry.report_health = health
    body = (
        {
            "text": "Example",
            "questions": {"risk": "Is there risk?"},
            "user_id": "fake-user",
        }
        if route == "/v1/classify"
        else call.model_dump(mode="json") | {"stream": stream}
    )
    async with respx.mock as mock, httpx.AsyncClient() as client:
        mock.post(entry.endpoint_url + PATHS[entry.api_type]).mock(
            return_value=httpx.Response(503)
            if failed
            else provider(
                entry.api_type,
                response(
                    entry.api_type,
                    text='{"risk":0.2}' if route == "/v1/classify" else "Final answer",
                ),
                stream,
            )
        )
        engine = Engine(client, registry, FakeDatabase(), Publisher())
        engine.side_effect_timeout = 0.03
        app = create_app()
        app.state.identity, app.state.engine = Identity(), engine

        async def receive() -> dict:
            return {
                "type": "http.request",
                "body": json.dumps(body).encode(),
                "more_body": False,
            }

        async def send(message: dict) -> None:
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "method": "POST",
            "scheme": "http",
            "path": route,
            "raw_path": route.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"content-type", b"application/json")],
            "server": ("test", 80),
            "client": ("test", 123),
        }
        await asyncio.wait_for(app(scope, receive, send), timeout=0.3)
        assert sent[0]["status"] == (503 if failed else 200)
        await asyncio.wait_for(
            asyncio.gather(*(event.wait() for event in started.values())), timeout=0.3
        )
        await asyncio.wait_for(engine.drain_background(), timeout=0.3)
        assert not engine.background_tasks
    assert set(cancelled) == {"health", "audit"}
    assert (
        "health_report_failed" in caplog.text and "audit_publish_failed" in caplog.text
    )


async def assert_forced_without_thinking(entry: Entry, call: Call, kind: str) -> None:
    entry = entry.model_copy(update={"api_type": kind, "request_settings": {}})
    forced = call.model_copy(
        update={"stream": False, "tool_choice": ToolChoice(name="fake_tool")}
    )
    with respx.mock as mock:
        route = mock.post(entry.endpoint_url + PATHS[kind]).mock(
            return_value=provider(kind, response(kind), False)
        )
        async with httpx.AsyncClient() as client:
            engine = Engine(client, FakeRegistry([entry]), FakeDatabase())
            events = [e async for e in engine.events(forced)]
            await engine.drain_background()
        body = json.loads(route.calls[0].request.content)
    assert "thinking" not in body
    expected = (
        {"type": "function", "name": "fake_tool"}
        if kind == "openai_responses"
        else {"type": "function", "function": {"name": "fake_tool"}}
    )
    assert body["tool_choice"] == expected
    assert events[-1]["tool_choice_applied"] is True


@pytest.mark.anyio
async def test_responses_entry_sends_forced_tool_without_thinking_setting(
    entry: Entry, call: Call
) -> None:
    await assert_forced_without_thinking(entry, call, "openai_responses")


@pytest.mark.anyio
async def test_chat_entry_sends_forced_tool_without_thinking_setting(
    entry: Entry, call: Call
) -> None:
    await assert_forced_without_thinking(entry, call, "openai_chat_completions")


@pytest.mark.anyio
async def test_client_disconnect_right_after_completed_still_publishes_audit(
    entry: Entry, call: Call
) -> None:
    from starlette.requests import ClientDisconnect

    sent, audits, reports = [], [], []

    class Publisher:
        async def publish(self, value: dict) -> None:
            audits.append(value)

    class Identity:
        async def authenticate(self, authorization: str | None) -> dict:
            return {"azp": "ooh-harness-api", "sub": "fake-service"}

    async def health(entry: Entry, status: str, reason: str | None) -> None:
        reports.append((status, reason))

    async with respx.mock as mock, httpx.AsyncClient() as client:
        mock.post(entry.endpoint_url + PATHS[entry.api_type]).mock(
            return_value=provider(entry.api_type, response(entry.api_type), True)
        )
        registry = FakeRegistry([entry])
        registry.report_health = health
        engine = Engine(client, registry, FakeDatabase(), Publisher())
        app = create_app()
        app.state.engine, app.state.identity = engine, Identity()

        async def receive() -> dict:
            return {
                "type": "http.request",
                "body": json.dumps(
                    call.model_dump(mode="json") | {"stream": True}
                ).encode(),
                "more_body": False,
            }

        async def send(message: dict) -> None:
            sent.append(message)
            if message["type"] == "http.response.body" and message.get(
                "body", b""
            ).startswith(b"data: "):
                event = json.loads(message["body"][6:])
                if event["type"] == "completed":
                    raise OSError("synthetic client disconnect after completed")

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "method": "POST",
            "scheme": "http",
            "path": "/v1/call",
            "raw_path": b"/v1/call",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"content-type", b"application/json")],
            "server": ("test", 80),
            "client": ("test", 123),
        }
        with pytest.raises(ClientDisconnect):
            await app(scope, receive, send)
        await asyncio.wait_for(engine.drain_background(), timeout=0.3)
        assert not engine.background_tasks
    assert not any(
        m["type"] == "http.response.body" and not m.get("more_body", False)
        for m in sent
    )
    assert len(audits) == 1 and audits[0]["payload"]["action"] == "model.call"
    assert (
        audits[0]["payload"]["outcome"] == "ok" and audits[0]["payload"]["tokens"] == 11
    )
    assert audits[0]["payload"]["cost_usd"] > 0
    assert reports == [("ok", None)]
