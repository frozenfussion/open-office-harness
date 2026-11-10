# SPDX-License-Identifier: AGPL-3.0-only
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from conftest import Harness

pytestmark = pytest.mark.anyio


def events(response: httpx.Response) -> list[dict[str, Any]]:
    return [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


async def test_health_and_storage_failure(h: Harness) -> None:
    h.client.headers.clear()
    assert (await h.client.get("/health")).json() == {"status": "ok"}
    h.store.fail_health = True
    response = await h.client.get("/health")
    assert response.status_code == 503
    assert "private diagnostic" not in response.text


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/api/me", None),
        ("post", "/api/conversations", {}),
        ("get", "/api/conversations", None),
        ("get", f"/api/conversations/{uuid4()}", None),
        ("post", f"/api/conversations/{uuid4()}/messages", {"content": "Question"}),
        ("post", "/api/uploads", None),
        ("get", "/api/events", None),
        ("get", "/api/files/example", None),
    ],
)
async def test_every_route_needs_token(
    h: Harness, method: str, path: str, body: Any
) -> None:
    h.client.headers.clear()
    response = await h.client.request(method, path, json=body)
    assert response.status_code == 401


@pytest.mark.parametrize(
    "changes",
    [
        {"aud": "ooh-control-centre"},
        {"iss": "https://wrong.test"},
        {"exp": int(time.time()) - 300},
        {"sub": ""},
    ],
)
async def test_bad_claims(h: Harness, changes: dict[str, Any]) -> None:
    h.client.headers["Authorization"] = f"Bearer {h.token(**changes)}"
    assert (await h.client.get("/api/me")).status_code == 401


async def test_me_and_own_conversations(h: Harness) -> None:
    response = await h.client.get("/api/me")
    assert response.json() == {
        "user_id": "test-user",
        "name": "Test user",
        "chat_tiers": [1, 2, 3],
        "skills": [{"name": "slides", "title": "Example skill"}],
    }
    first = await h.conversation()
    second = await h.conversation()
    rows = (await h.client.get("/api/conversations?limit=1")).json()
    assert [row["id"] for row in rows] == [second]
    rows = (await h.client.get(f"/api/conversations?before={second}")).json()
    assert [row["id"] for row in rows] == [first]
    assert (await h.client.get(f"/api/conversations/{first}")).json()["messages"] == []
    h.client.headers["Authorization"] = f"Bearer {h.token(sub='other-user')}"
    assert (await h.client.get("/api/conversations")).json() == []
    assert (await h.client.get(f"/api/conversations/{first}")).status_code == 404
    assert (await h.send(first)).status_code == 404
    assert (await h.client.get(f"/api/conversations?before={first}")).status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/api/me?user_id=other",
        "/health?extra=1",
        "/api/conversations?limit=0",
        "/api/conversations?limit=101",
        "/api/conversations?before=bad",
        "/api/conversations?limit=2&limit=3",
        "/api/conversations/bad",
        "/api/events?x=1",
        "/api/files/example?x=1",
    ],
)
async def test_invalid_query_or_path(h: Harness, path: str) -> None:
    assert (await h.client.get(path)).status_code == 400


@pytest.mark.parametrize("body", [{"user_id": "other-user"}, [], None])
async def test_invalid_create(h: Harness, body: Any) -> None:
    assert (await h.client.post("/api/conversations", json=body)).status_code == 400


@pytest.mark.parametrize(
    "body",
    [
        {"content": ""},
        {"content": " "},
        {"content": 2},
        {"content": "Question", "tier": 0},
        {"content": "Question", "tier": True},
        {"content": "Question", "user_id": "other-user"},
        {},
        {"content": "Question", "attachments": []},
    ],
)
async def test_invalid_message(h: Harness, body: Any) -> None:
    identifier = await h.conversation()
    assert (
        await h.client.post(f"/api/conversations/{identifier}/messages", json=body)
    ).status_code == 400
    assert h.store.rows[UUID(identifier)]["messages"] == []


@pytest.mark.parametrize(
    "method,path",
    [("post", "/api/uploads"), ("get", "/api/events"), ("get", "/api/files/example")],
)
async def test_future_routes(h: Harness, method: str, path: str) -> None:
    response = await h.client.request(method, path)
    assert response.status_code == 503
    assert response.json()["code"] == "not_built_yet"


async def test_stream_and_history(h: Harness) -> None:
    identifier = await h.conversation()
    text = "Question" * 10
    response = await h.send(identifier, content=text)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Accel-Buffering"] == "no"
    stream = events(response)
    assert [event["type"] for event in stream] == ["delta", "completed"]
    assert stream[-1]["tier"] == 1
    assert stream[-1]["usage"] == {"input_tokens": 4, "output_tokens": 2}
    request = json.loads(h.gateway.calls[0].request.content)
    assert request["user_id"] == "test-user"
    assert request["messages"] == [{"role": "user", "content": text}]
    check = json.loads(h.check.calls[0].request.content)
    assert check == {"user_id": "test-user", "action": "chat.tier", "target": "1"}
    row = (await h.client.get(f"/api/conversations/{identifier}")).json()
    assert row["title"] == text[:60]
    assert [message["outcome"] for message in row["messages"]] == [
        "completed",
        "completed",
    ]
    assert row["messages"][1]["content"] == "Hello"
    await h.send(identifier)
    assert len(json.loads(h.gateway.calls[-1].request.content)["messages"]) == 3


@pytest.mark.parametrize("failure", ["timeout", "denied", "bad_body", "http"])
async def test_rights_fail_closed(h: Harness, failure: str) -> None:
    identifier = await h.conversation()
    if failure == "timeout":
        h.rights.mock(side_effect=httpx.ConnectError("private error"))
    elif failure == "denied":
        h.check.respond(json={"allowed": False})
    elif failure == "bad_body":
        h.check.respond(json={"allowed": "true"})
    else:
        h.check.respond(503)
    response = await h.send(identifier)
    assert response.status_code == (403 if failure == "denied" else 503)
    assert response.json()["code"] == (
        "tier_not_allowed" if failure == "denied" else "rights_unavailable"
    )
    assert not h.gateway.called
    assert not h.store.rows[UUID(identifier)]["messages"]


async def test_no_tier_and_crafted_tier(h: Harness) -> None:
    identifier = await h.conversation()
    h.rights.respond(json={"chat_tiers": [], "skills": []})
    response = await h.send(identifier)
    assert response.json() == {
        "code": "no_tier",
        "message": "You have no chat tier yet. An admin can grant one.",
    }
    h.check.respond(json={"allowed": False})
    response = await h.send(identifier, tier=5)
    assert response.status_code == 403
    assert response.json()["message"] == "You don't have tier 5. An admin can grant it."


async def test_tools_and_fixed_sentence(h: Harness) -> None:
    identifier = await h.conversation()
    h.gateway.respond(
        text=h.sse(
            [
                {"type": "delta", "text": "Plan: "},
                {
                    "type": "tool_call",
                    "id": "tool-1",
                    "name": "slides",
                    "arguments": {"topic": "Example"},
                },
                h.completed(),
            ]
        ),
        headers={"Content-Type": "text/event-stream"},
    )
    response = await h.send(identifier)
    stream = events(response)
    sentence = (
        "I would use the Example skill skill for this. "
        "Skills are switched on in the next stage."
    )
    assert stream[1] == {"type": "delta", "text": sentence}
    assert stream[-1]["type"] == "completed"
    assert h.store.rows[UUID(identifier)]["messages"][-1]["outcome"] == "tool_requested"
    assert (
        h.store.rows[UUID(identifier)]["messages"][-1]["content"] == "Plan: " + sentence
    )
    request = json.loads(h.gateway.calls[-1].request.content)
    assert [tool["name"] for tool in request["tools"]] == ["slides"]
    h.rights.respond(json={"chat_tiers": [1], "skills": []})
    h.gateway.respond(
        text=h.sse([h.completed()]), headers={"Content-Type": "text/event-stream"}
    )
    await h.send(identifier)
    request = json.loads(h.gateway.calls[-1].request.content)
    assert request["tools"] == []
    assert all(message["role"] == "user" for message in request["messages"])


def test_schema_copy() -> None:
    root = Path(__file__).resolve().parents[3]
    assert (
        root / "services/harness-api/harness_api/schemas/slides.json"
    ).read_bytes() == (root / "contracts/skills/slides/input.schema.json").read_bytes()


@pytest.mark.parametrize(
    "code,status",
    [
        ("no_model", 503),
        ("rate_limited", 429),
        ("budget_exceeded", 503),
        ("unavailable", 503),
        ("registry_unavailable", 503),
    ],
)
async def test_gateway_json_errors(h: Harness, code: str, status: int) -> None:
    identifier = await h.conversation()
    h.gateway.respond(
        status, json={"code": code, "message": "private upstream message"}
    )
    response = await h.send(identifier)
    assert response.status_code == status
    assert response.json()["code"] == (
        "unavailable" if code == "registry_unavailable" else code
    )
    assert "private upstream" not in response.text
    assert response.headers["Content-Type"] == "application/json"


async def test_budget_fallback_and_recheck(h: Harness) -> None:
    identifier = await h.conversation()
    h.gateway.mock(
        side_effect=[
            httpx.Response(503, json={"code": "budget_exceeded"}),
            httpx.Response(
                200,
                text=h.sse([{"type": "delta", "text": "Hello"}, h.completed()]),
                headers={"Content-Type": "text/event-stream"},
            ),
        ]
    )
    response = await h.send(identifier, tier=3)
    assert response.status_code == 200
    assert [json.loads(call.request.content)["tier"] for call in h.gateway.calls] == [
        3,
        1,
    ]
    assert [json.loads(call.request.content)["target"] for call in h.check.calls] == [
        "3",
        "1",
    ]
    assert (
        events(response)[-1]["note"]
        == "tier 3 is over its daily budget; answered with tier 1"
    )
    assert h.store.rows[UUID(identifier)]["messages"][-1]["tier"] == 1


class Broken(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'data: {"type":"delta","text":"Partial"}\n\n'
        raise httpx.ReadError("private stream error")


async def test_partial_stored_failed(h: Harness) -> None:
    identifier = await h.conversation()
    h.gateway.respond(stream=Broken(), headers={"Content-Type": "text/event-stream"})
    response = await h.send(identifier)
    stream = events(response)
    assert [event["type"] for event in stream] == ["delta", "failed"]
    assert stream[-1]["error"]["code"] == "unavailable"
    last = h.store.rows[UUID(identifier)]["messages"][-1]
    assert last["content"] == "Partial"
    assert last["outcome"] == "failed"


@pytest.mark.parametrize(
    "code",
    [
        "no_model",
        "rate_limited",
        "budget_exceeded",
        "unavailable",
        "registry_unavailable",
    ],
)
async def test_gateway_failed_event(h: Harness, code: str) -> None:
    identifier = await h.conversation()
    h.gateway.respond(
        text=h.sse(
            [
                {"type": "delta", "text": "Partial"},
                {"type": "failed", "error": {"code": code, "message": "private"}},
            ]
        ),
        headers={"Content-Type": "text/event-stream"},
    )
    response = await h.send(identifier)
    assert events(response)[-1]["type"] == "failed"
    assert "private" not in response.text
    assert h.store.rows[UUID(identifier)]["messages"][-1]["outcome"] == "failed"


async def test_disconnect_persists_partial(h: Harness) -> None:
    from starlette.requests import ClientDisconnect

    identifier = await h.conversation()
    received = False
    delivered = []

    async def receive() -> dict[str, Any]:
        nonlocal received
        if received:
            raise AssertionError("Unexpected request read")
        received = True
        return {
            "type": "http.request",
            "body": b'{"content":"Question"}',
            "more_body": False,
        }

    async def send(event: dict[str, Any]) -> None:
        delivered.append(event)
        if event["type"] == "http.response.body":
            raise OSError("Browser disconnected")

    scope = {
        "type": "http",
        "asgi": {"spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": f"/api/conversations/{identifier}/messages",
        "query_string": b"",
        "headers": [
            (b"content-type", b"application/json"),
            (b"authorization", h.client.headers["Authorization"].encode()),
        ],
        "server": ("test", 80),
        "client": ("127.0.0.1", 1),
        "root_path": "",
    }
    with pytest.raises(ClientDisconnect):
        await h.app(scope, receive, send)
    assert delivered[0]["status"] == 200
    last = h.store.rows[UUID(identifier)]["messages"][-1]
    assert last["content"] == "Hello" and last["outcome"] == "failed"


@pytest.mark.parametrize(
    "kind",
    ["empty", "malformed", "incomplete", "wrong_type", "wrong_tier", "early_failure"],
)
async def test_failure_before_first_browser_byte(h: Harness, kind: str) -> None:
    identifier = await h.conversation()
    bodies = {
        "empty": "",
        "malformed": "data: not-json\n\n",
        "incomplete": 'data: {"type":"delta","text":"lost"}',
        "wrong_type": h.sse([{"type": "unknown"}]),
        "wrong_tier": h.sse([h.completed(2)]),
        "early_failure": h.sse(
            [{"type": "failed", "error": {"code": "unavailable", "message": "private"}}]
        ),
    }
    h.gateway.respond(text=bodies[kind], headers={"Content-Type": "text/event-stream"})
    response = await h.send(identifier)
    assert response.status_code == 503
    assert response.json()["code"] == "unavailable"
    assert h.store.rows[UUID(identifier)]["messages"][-1]["outcome"] == "failed"


async def test_budget_fallback_checks_current_grant(h: Harness) -> None:
    identifier = await h.conversation()
    h.gateway.respond(503, json={"code": "budget_exceeded"})
    h.check.mock(
        side_effect=[
            httpx.Response(200, json={"allowed": True}),
            httpx.Response(200, json={"allowed": False}),
        ]
    )
    response = await h.send(identifier, tier=3)
    assert response.status_code == 403
    assert h.gateway.call_count == 1


async def test_upstream_token_and_jwks_cache(h: Harness) -> None:
    await h.client.get("/api/me")
    await h.client.get("/api/me")
    assert h.jwks.call_count == 1
    assert h.token_route.call_count == 1
    h.app.state.auth.token_until = 0
    h.app.state.auth.keys_until = 0
    h.app.state.auth.keys_refresh_after = 0
    await h.client.get("/api/me")
    assert h.jwks.call_count == 2
    assert h.token_route.call_count == 2
    request = h.token_route.calls[-1].request
    assert request.content.startswith(b"grant_type=client_credentials")


async def test_jwks_unavailable_is_unauthorized(h: Harness) -> None:
    h.jwks.respond(503)
    assert (await h.client.get("/api/me")).status_code == 401
    assert not h.rights.called


async def test_logs_never_include_text_or_credentials(
    h: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    from harness_api.app import JsonFormatter

    identifier = await h.conversation()
    await h.send(identifier, content="synthetic-private-chat-content")
    assert "synthetic-private-chat-content" not in caplog.text
    assert "fake-client-credential" not in caplog.text
    assert h.client.headers["Authorization"] not in caplog.text
    record = logging.LogRecord(
        "httpx",
        logging.ERROR,
        "",
        0,
        "synthetic-private-chat-content fake-client-credential",
        (),
        None,
    )
    formatted = JsonFormatter().format(record)
    assert json.loads(formatted)["level"] == "error"
    assert "synthetic-private-chat-content" not in formatted
    assert "fake-client-credential" not in formatted


async def test_upload_bad_query(h: Harness) -> None:
    assert (await h.client.post("/api/uploads?user_id=other")).status_code == 400


@pytest.mark.parametrize("azp", [None, "another-client"])
async def test_audience_does_not_require_workspace_client(
    h: Harness, azp: str | None
) -> None:
    import jwt

    claims = jwt.decode(h.token(), options={"verify_signature": False})
    if azp is None:
        claims.pop("azp")
    else:
        claims["azp"] = azp
    token = jwt.encode(
        claims, h.private_key, algorithm="RS256", headers={"kid": "test"}
    )
    h.client.headers["Authorization"] = f"Bearer {token}"
    assert (await h.client.get("/api/me")).status_code == 200


async def test_lowest_tier_from_unsorted_rights(h: Harness) -> None:
    identifier = await h.conversation()
    h.rights.respond(json={"chat_tiers": [3, 1], "skills": []})
    response = await h.send(identifier)
    assert response.status_code == 200
    assert events(response)[-1]["tier"] == 1
    assert json.loads(h.gateway.calls[-1].request.content)["tier"] == 1
    assert json.loads(h.check.calls[-1].request.content)["target"] == "1"


async def test_unknown_signing_keys_are_throttled(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    import jwt

    import harness_api.auth as auth_module

    now = 1000.0
    monkeypatch.setattr(auth_module, "time", SimpleNamespace(monotonic=lambda: now))
    assert (await h.client.get("/api/me")).status_code == 200
    for index in range(5):
        claims = jwt.decode(h.token(), options={"verify_signature": False})
        token = jwt.encode(
            claims,
            h.private_key,
            algorithm="RS256",
            headers={"kid": f"unknown-{index}"},
        )
        h.client.headers["Authorization"] = f"Bearer {token}"
        assert (await h.client.get("/api/me")).status_code == 401
    assert h.jwks.call_count == 1
    now += 31
    assert (await h.client.get("/api/me")).status_code == 401
    assert h.jwks.call_count == 2
    assert (await h.client.get("/api/me")).status_code == 401
    assert h.jwks.call_count == 2
    h.client.headers["Authorization"] = f"Bearer {h.token()}"
    assert (await h.client.get("/api/me")).status_code == 200


async def test_failed_signing_key_fetch_is_throttled(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    import jwt

    import harness_api.auth as auth_module

    now = 1000.0
    monkeypatch.setattr(auth_module, "time", SimpleNamespace(monotonic=lambda: now))
    h.jwks.respond(503)
    for _ in range(3):
        assert (await h.client.get("/api/me")).status_code == 401
    assert h.jwks.call_count == 1
    now += 31
    h.jwks.respond(
        json={
            "keys": [
                {
                    **json.loads(
                        jwt.algorithms.RSAAlgorithm.to_jwk(h.private_key.public_key())
                    ),
                    "kid": "test",
                    "alg": "RS256",
                }
            ]
        }
    )
    assert (await h.client.get("/api/me")).status_code == 200
    assert h.jwks.call_count == 2


@pytest.mark.parametrize(
    "problem,expected",
    [
        ("rights", ("rights_error", "rights_unavailable")),
        ("gateway", ("gateway_error", "no_model")),
        ("stream", ("gateway_error", "unavailable")),
        ("database", ("database_error", "unavailable")),
        ("token", ("token_error", "unavailable")),
        ("authentication", ("authentication_error", "unauthorized")),
    ],
)
async def test_fixed_failure_logs(
    h: Harness,
    caplog: pytest.LogCaptureFixture,
    problem: str,
    expected: tuple[str, str],
) -> None:
    from harness_api.diagnostics import JsonFormatter

    identifier = await h.conversation()
    if problem == "rights":
        h.rights.mock(side_effect=httpx.ConnectError("synthetic-private-upstream"))
    elif problem == "gateway":
        h.gateway.respond(
            404, json={"code": "no_model", "message": "synthetic-private-upstream"}
        )
    elif problem == "stream":
        h.gateway.respond(
            stream=Broken(), headers={"Content-Type": "text/event-stream"}
        )
    elif problem == "database":
        h.store.fail_health = True
    elif problem == "token":
        h.token_route.respond(503, json={"message": "fake-client-credential"})
    else:
        h.client.headers.clear()
    if problem == "database":
        response = await h.client.get("/health")
    else:
        response = await h.send(identifier, content="synthetic-private-chat-content")
    assert response.status_code in {200, 401, 503}
    lines = [
        JsonFormatter().format(record)
        for record in caplog.records
        if record.name == "harness_api"
    ]
    parsed = [json.loads(line) for line in lines]
    assert any((line["event"], line["code"]) == expected for line in parsed)
    for line in parsed:
        assert set(line) <= {"level", "event", "code", "tier"}
    combined = "\n".join(lines)
    for sensitive in (
        "synthetic-private-chat-content",
        "synthetic-private-upstream",
        "fake-client-credential",
        "fake-service-token",
        "test-user",
        h.client.headers.get("Authorization", "not-a-real-token"),
    ):
        assert sensitive not in combined
    if problem == "stream":
        assert parsed[-1]["tier"] == 1
