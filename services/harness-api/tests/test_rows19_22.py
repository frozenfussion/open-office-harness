# SPDX-License-Identifier: AGPL-3.0-only
import json
from dataclasses import replace
from typing import Any
from uuid import UUID

import anyio
import httpx
import pytest
from conftest import SETTINGS, Harness
from test_routes import events

from harness_api.diagnostics import JsonFormatter
from harness_api.upstream import TITLE_PROMPT

pytestmark = pytest.mark.anyio


async def test_me_passes_thinking_and_requestable_metadata(h: Harness) -> None:
    requestable = [
        {"tier": 2, "title": "Example model", "requested": None},
        {"tier": 3, "title": "Another example", "requested": "pending"},
        {"tier": 4, "title": "Higher example", "requested": "rejected"},
    ]
    h.rights.respond(
        json={
            "chat_tiers": [1],
            "skills": [],
            "chat_tier_thinking_switch": {"1": False},
            "requestable_tiers": requestable,
        }
    )
    response = await h.client.get("/api/me")
    assert response.status_code == 200
    assert response.json()["chat_tier_thinking_switch"] == {"1": False}
    assert response.json()["requestable_tiers"] == requestable


@pytest.mark.parametrize(
    "change",
    [
        {"chat_tier_thinking_switch": {"1": "true"}},
        {"chat_tier_thinking_switch": {"1": 1}},
        {"requestable_tiers": None},
        {"requestable_tiers": [{"tier": 2, "title": "Example", "requested": False}]},
    ],
)
async def test_bad_rights_metadata_is_closed(
    h: Harness, change: dict[str, Any]
) -> None:
    h.rights.respond(json={"chat_tiers": [1], "skills": [], **change})
    response = await h.client.get("/api/me")
    assert response.status_code == 503
    assert response.json()["code"] == "rights_unavailable"


@pytest.mark.parametrize(
    "choice,applied", [(None, False), (True, False), (False, False), (False, True)]
)
async def test_thinking_choice_and_actual_result(
    h: Harness, choice: bool | None, applied: bool
) -> None:
    identifier = await h.conversation()
    h.gateway.respond(
        text=h.sse([{**h.completed(), "thinking_applied": applied}]),
        headers={"Content-Type": "text/event-stream"},
    )
    response = await h.send(
        identifier, **({} if choice is None else {"thinking": choice})
    )
    assert response.status_code == 200
    assert json.loads(h.gateway.calls.last.request.content)["thinking"] is (
        True if choice is None else choice
    )
    assert events(response)[0]["thinking_applied"] is applied
    row = (await h.client.get(f"/api/conversations/{identifier}")).json()
    assert all("thinking_applied" not in message for message in row["messages"])


@pytest.mark.parametrize("choice", [None, 0, 1, "false", "true", [], {}])
async def test_thinking_must_be_boolean(h: Harness, choice: Any) -> None:
    identifier = await h.conversation()
    assert (await h.send(identifier, thinking=choice)).status_code == 400
    assert not h.gateway.called


async def test_budget_fallback_preserves_thinking(h: Harness) -> None:
    identifier = await h.conversation()
    h.gateway.mock(
        side_effect=[
            httpx.Response(503, json={"code": "budget_exceeded"}),
            httpx.Response(
                200,
                text=h.sse([{**h.completed(), "thinking_applied": False}]),
                headers={"Content-Type": "text/event-stream"},
            ),
        ]
    )
    response = await h.send(identifier, tier=3, thinking=False)
    assert response.status_code == 200
    calls = [json.loads(call.request.content) for call in h.gateway.calls]
    assert [call["tier"] for call in calls] == [3, 1]
    assert all(call["thinking"] is False for call in calls)
    assert events(response)[-1]["thinking_applied"] is False


async def test_invalid_thinking_applied_is_not_accepted(h: Harness) -> None:
    identifier = await h.conversation()
    h.gateway.respond(
        text=h.sse([{**h.completed(), "thinking_applied": "false"}]),
        headers={"Content-Type": "text/event-stream"},
    )
    assert (await h.send(identifier)).status_code == 503


@pytest.mark.parametrize("reason", [None, "", "Example reason", "x" * 300])
async def test_tier_request_uses_verified_user(h: Harness, reason: str | None) -> None:
    response = await h.client.post(
        "/api/tier-requests", json={"tier": 2, "reason": reason}
    )
    assert response.status_code == 201
    assert response.json() == {
        "id": "00000000-0000-4000-8000-000000000010",
        "status": "pending",
    }
    call = h.tier_requests.calls.last.request
    assert json.loads(call.content) == {
        "user_id": "test-user",
        "tier": 2,
        "reason": reason,
    }
    assert call.headers["Authorization"] == "Bearer fake-service-token"
    assert not h.observe.called and not h.gateway.called


async def test_tier_request_reason_optional(h: Harness) -> None:
    assert (
        await h.client.post("/api/tier-requests", json={"tier": 2})
    ).status_code == 201
    assert json.loads(h.tier_requests.calls.last.request.content)["reason"] is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"tier": 0},
        {"tier": -1},
        {"tier": True},
        {"tier": "2"},
        {"tier": 2.5},
        {"tier": 2, "user_id": "other-user"},
        {"tier": 2, "reason": "x" * 301},
        {"tier": 2, "reason": False},
        {"tier": 2, "extra": 1},
    ],
)
async def test_tier_request_bad_input(h: Harness, body: Any) -> None:
    assert (await h.client.post("/api/tier-requests", json=body)).status_code == 400
    assert not h.tier_requests.called


@pytest.mark.parametrize("query", ["?user_id=other", "?limit=1"])
async def test_tier_request_rejects_query(h: Harness, query: str) -> None:
    assert (
        await h.client.post("/api/tier-requests" + query, json={"tier": 2})
    ).status_code == 400
    assert not h.tier_requests.called


@pytest.mark.parametrize("wrong_audience", [True, False])
async def test_tier_request_needs_token(h: Harness, wrong_audience: bool) -> None:
    if wrong_audience:
        h.client.headers["Authorization"] = (
            f"Bearer {h.token(aud='ooh-control-centre')}"
        )
    else:
        h.client.headers.clear()
    assert (
        await h.client.post("/api/tier-requests", json={"tier": 2})
    ).status_code == 401
    assert not h.tier_requests.called


@pytest.mark.parametrize(
    "status,code",
    [
        (403, "not_approved"),
        (400, "tier_not_requestable"),
        (409, "already_requested"),
        (409, "too_soon"),
        (429, "too_many_requests"),
    ],
)
async def test_tier_request_preserves_control_centre_decision(
    h: Harness, caplog: pytest.LogCaptureFixture, status: int, code: str
) -> None:
    private = "synthetic-private-model-request-reason"
    h.tier_requests.respond(status, json={"code": code, "message": private})
    response = await h.client.post(
        "/api/tier-requests", json={"tier": 2, "reason": private}
    )
    assert response.status_code == status
    assert response.json()["code"] == code
    assert private not in response.text and private not in caplog.text
    assert all(
        private not in JsonFormatter().format(record) for record in caplog.records
    )


@pytest.mark.parametrize(
    "problem",
    ["connection", "timeout", "http", "json", "bad_id", "bad_status", "bad_error"],
)
async def test_tier_request_unavailable_is_closed(h: Harness, problem: str) -> None:
    if problem == "connection":
        h.tier_requests.mock(side_effect=httpx.ConnectError("private"))
    elif problem == "timeout":
        h.tier_requests.mock(side_effect=httpx.ReadTimeout("private"))
    elif problem == "http":
        h.tier_requests.respond(503)
    elif problem == "json":
        h.tier_requests.respond(201, text="not-json")
    elif problem == "bad_id":
        h.tier_requests.respond(201, json={"id": "bad", "status": "pending"})
    elif problem == "bad_status":
        h.tier_requests.respond(
            201,
            json={"id": "00000000-0000-4000-8000-000000000010", "status": "approved"},
        )
    else:
        h.tier_requests.respond(
            409, json={"code": "private-code", "message": "private"}
        )
    response = await h.client.post("/api/tier-requests", json={"tier": 2})
    assert response.status_code == 503
    assert response.json()["code"] == "rights_unavailable"


async def test_title_only_if_default_is_still_present(h: Harness) -> None:
    identifier = await h.conversation()

    def chat_reply(request: httpx.Request) -> httpx.Response:
        h.store.rows[UUID(identifier)]["title"] = "An existing custom title"
        return httpx.Response(
            200,
            text=h.sse([h.completed()]),
            headers={"Content-Type": "text/event-stream"},
        )

    h.gateway.mock(side_effect=chat_reply)
    response = await h.send(identifier)
    assert events(response)[-1]["type"] == "completed"
    assert not h.title_gateway.called
    assert h.store.rows[UUID(identifier)]["title"] == "An existing custom title"


async def test_title_does_not_overwrite_a_concurrent_rename(h: Harness) -> None:
    identifier = await h.conversation()

    def title_reply(request: httpx.Request) -> httpx.Response:
        h.store.rows[UUID(identifier)]["title"] = "Concurrent custom title"
        return httpx.Response(200, json={"content": "Generated title"})

    h.title_gateway.mock(side_effect=title_reply)
    assert events(await h.send(identifier))[-1]["type"] == "completed"
    assert h.store.rows[UUID(identifier)]["title"] == "Concurrent custom title"


async def test_title_deadline_closes_stream_after_completed(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    import harness_api.app as app_module

    assert app_module.TITLE_TIMEOUT_SECONDS == 20
    monkeypatch.setattr(app_module, "TITLE_TIMEOUT_SECONDS", 0.01)
    identifier = await h.conversation()

    async def slow_title(request: httpx.Request) -> httpx.Response:
        assert set(request.extensions["timeout"].values()) == {20}
        await anyio.sleep(0.1)
        return httpx.Response(200, json={"content": "Too late"})

    h.title_gateway.mock(side_effect=slow_title)
    result = events(await h.send(identifier))
    assert [event["type"] for event in result] == ["delta", "completed"]
    assert h.store.rows[UUID(identifier)]["title"] == "Question"


@pytest.mark.parametrize("prompt", ["", "Synthetic chat prompt"])
async def test_title_has_only_its_own_system_instruction(
    h: Harness, prompt: str
) -> None:
    h.app.state.upstream.settings = replace(SETTINGS, system_prompt=prompt)
    identifier = await h.conversation()
    h.title_gateway.respond(json={"content": "A useful short title"})
    await h.send(identifier)
    messages = json.loads(h.title_gateway.calls.last.request.content)["messages"]
    assert [message for message in messages if message["role"] == "system"] == [
        {"role": "system", "content": TITLE_PROMPT}
    ]


async def test_title_uses_actual_budget_fallback_tier(h: Harness) -> None:
    identifier = await h.conversation()
    h.gateway.mock(
        side_effect=[
            httpx.Response(503, json={"code": "budget_exceeded"}),
            httpx.Response(
                200,
                text=h.sse([h.completed()]),
                headers={"Content-Type": "text/event-stream"},
            ),
        ]
    )
    h.title_gateway.respond(json={"content": "A useful short title"})
    await h.send(identifier, tier=3)
    body = json.loads(h.title_gateway.calls.last.request.content)
    assert body["tier"] == 1
    assert body["user_id"] == "title-test-user"
    assert [json.loads(call.request.content)["target"] for call in h.check.calls] == [
        "3",
        "1",
        "1",
    ]


@pytest.mark.parametrize("partial", [False, True])
async def test_missing_thinking_applied_is_an_unexpected_answer(
    h: Harness, partial: bool
) -> None:
    identifier = await h.conversation()
    completion = h.completed()
    completion.pop("thinking_applied")
    prefix = [{"type": "delta", "text": "Partial answer"}] if partial else []
    h.gateway.respond(
        text=h.sse([*prefix, completion]), headers={"Content-Type": "text/event-stream"}
    )
    response = await h.send(identifier)
    if partial:
        assert response.status_code == 200
        result = events(response)
        assert [event["type"] for event in result] == ["delta", "failed"]
        assert result[-1]["error"]["code"] == "unavailable"
    else:
        assert response.status_code == 503
        assert response.json()["code"] == "unavailable"
    assert h.store.rows[UUID(identifier)]["messages"][-1]["outcome"] == "failed"
    assert not h.title_gateway.called


@pytest.mark.parametrize(
    "answer,status",
    [
        ("success", 201),
        ("invalid_input", 400),
        ("unauthorized", 401),
        ("not_approved", 403),
        ("tier_not_requestable", 400),
        ("already_requested", 409),
        ("too_soon", 409),
        ("too_many_requests", 429),
        ("unavailable", 503),
    ],
)
async def test_marked_tier_reason_absent_from_every_log_record(
    h: Harness, caplog: pytest.LogCaptureFixture, answer: str, status: int
) -> None:
    import logging

    marker = "MARKED_TIER_REASON_NEVER_LOG_7f3c19"
    caplog.set_level(logging.DEBUG)
    body = {"tier": 2, "reason": marker}
    if answer == "unauthorized":
        h.client.headers.clear()
    elif answer == "invalid_input":
        body["tier"] = 0
    elif answer != "success":
        h.tier_requests.respond(status, json={"code": answer, "message": marker})
    response = await h.client.post("/api/tier-requests", json=body)
    assert response.status_code == status
    if h.tier_requests.called:
        assert (
            json.loads(h.tier_requests.calls.last.request.content)["reason"] == marker
        )
    assert caplog.records
    assert marker not in caplog.text
    for record in caplog.records:
        assert marker not in record.getMessage()
        assert marker not in repr(record.__dict__)
        assert marker not in JsonFormatter().format(record)


async def test_too_soon_uses_the_specified_message(h: Harness) -> None:
    h.tier_requests.respond(409, json={"code": "too_soon", "message": "Upstream text"})
    response = await h.client.post("/api/tier-requests", json={"tier": 2})
    assert response.status_code == 409
    assert response.json() == {
        "code": "too_soon",
        "message": "You can ask for this model again 7 days after the last answer.",
    }
