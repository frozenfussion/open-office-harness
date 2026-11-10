# SPDX-License-Identifier: AGPL-3.0-only
import json
from uuid import UUID

import httpx
import pytest
from conftest import Harness
from test_routes import events

from harness_api.diagnostics import JsonFormatter
from harness_api.upstream import TITLE_PROMPT

pytestmark = pytest.mark.anyio


async def test_title_after_completed_uses_lowest_tier_and_preserves_updated_time(
    h: Harness,
) -> None:
    identifier = await h.conversation()
    h.gateway.respond(
        text=h.sse([{"type": "delta", "text": "First answer"}, h.completed(3)]),
        headers={"Content-Type": "text/event-stream"},
    )
    h.title_gateway.respond(json={"content": '  "A useful short title."  '})
    h.rights.respond(json={"chat_tiers": [3, 1], "skills": []})
    updated = None

    def title_reply(request: httpx.Request) -> httpx.Response:
        nonlocal updated
        updated = h.store.rows[UUID(identifier)]["updated_at"]
        return httpx.Response(200, json={"content": '  "A useful short title."  '})

    h.title_gateway.mock(side_effect=title_reply)
    response = await h.send(identifier, tier=3, content="First question")
    result = events(response)
    assert [event["type"] for event in result] == ["delta", "completed", "title"]
    assert result[-1] == {
        "type": "title",
        "conversation_id": identifier,
        "title": "A useful short title",
    }
    call = h.title_gateway.calls.last.request
    body = json.loads(call.content)
    assert body == {
        "purpose": "chat",
        "tier": 1,
        "user_id": "test-user",
        "stream": False,
        "tools": [],
        "messages": [
            {"role": "system", "content": TITLE_PROMPT},
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
        ],
    }
    assert call.headers["Authorization"] == "Bearer fake-service-token"
    assert [json.loads(call.request.content)["target"] for call in h.check.calls] == [
        "3",
        "1",
    ]
    row = h.store.rows[UUID(identifier)]
    assert row["title"] == "A useful short title"
    assert row["updated_at"] == updated
    assert len(row["messages"]) == 2
    assert (await h.client.get(f"/api/conversations/{identifier}")).json()[
        "title"
    ] == "A useful short title"
    assert (await h.client.get("/api/conversations")).json()[0][
        "title"
    ] == "A useful short title"


async def test_title_only_after_first_completed_answer(h: Harness) -> None:
    identifier = await h.conversation()
    h.title_gateway.respond(json={"content": "A useful short title"})
    assert events(await h.send(identifier))[-1]["type"] == "title"
    assert events(await h.send(identifier))[-1]["type"] == "completed"
    assert h.title_gateway.call_count == 1
    assert h.store.rows[UUID(identifier)]["title"] == "A useful short title"


@pytest.mark.parametrize(
    "code,status",
    [
        ("no_model", 404),
        ("rate_limited", 429),
        ("budget_exceeded", 503),
        ("unavailable", 503),
        ("registry_unavailable", 503),
    ],
)
async def test_title_failure_keeps_old_title_and_does_not_retry(
    h: Harness, caplog: pytest.LogCaptureFixture, code: str, status: int
) -> None:
    identifier = await h.conversation()
    h.title_gateway.respond(
        status, json={"code": code, "message": "synthetic-private-provider-text"}
    )
    response = await h.send(identifier, content="Original question")
    assert response.status_code == 200
    assert events(response)[-1]["type"] == "completed"
    assert h.store.rows[UUID(identifier)]["title"] == "Original question"
    logs = [
        json.loads(JsonFormatter().format(record))
        for record in caplog.records
        if getattr(record, "event", None) == "title_failed"
    ]
    assert len(logs) == 1 and logs[0]["code"] == code
    assert "synthetic-private-provider-text" not in caplog.text
    await h.send(identifier, content="Next question")
    assert h.title_gateway.call_count == 1
    assert h.store.rows[UUID(identifier)]["title"] == "Original question"


@pytest.mark.parametrize(
    "value,expected",
    [
        ('  "Useful conversation title."  ', "Useful conversation title"),
        ('"Useful conversation title".', "Useful conversation title"),
        ("  ‘Useful conversation title.’  ", "Useful conversation title"),
        ("a" * 80 + ".", "a" * 60),
    ],
)
async def test_title_cleanup(h: Harness, value: str, expected: str) -> None:
    identifier = await h.conversation()
    h.title_gateway.respond(json={"content": value})
    response = await h.send(identifier)
    assert events(response)[-1]["title"] == expected
    assert h.store.rows[UUID(identifier)]["title"] == expected


async def test_title_context_is_cut_to_2000_characters(h: Harness) -> None:
    identifier = await h.conversation()
    question = "q" * 2100
    answer = "a" * 2200
    h.gateway.respond(
        text=h.sse([{"type": "delta", "text": answer}, h.completed()]),
        headers={"Content-Type": "text/event-stream"},
    )
    h.title_gateway.respond(json={"content": "A useful short title"})
    await h.send(identifier, content=question)
    messages = json.loads(h.title_gateway.calls.last.request.content)["messages"]
    assert messages == [
        {"role": "system", "content": TITLE_PROMPT},
        {"role": "user", "content": question[:2000]},
        {"role": "assistant", "content": answer[:2000]},
    ]


@pytest.mark.parametrize(
    "failure",
    [
        "timeout",
        "connection",
        "invalid_json",
        "empty",
        "missing",
        "invalid_content",
        "private_code",
    ],
)
async def test_invalid_title_response_is_best_effort(h: Harness, failure: str) -> None:
    identifier = await h.conversation()
    if failure == "timeout":
        h.title_gateway.mock(side_effect=httpx.ReadTimeout("synthetic-private-text"))
    elif failure == "connection":
        h.title_gateway.mock(side_effect=httpx.ConnectError("synthetic-private-text"))
    elif failure == "invalid_json":
        h.title_gateway.respond(text="not-json")
    elif failure == "private_code":
        h.title_gateway.respond(503, json={"code": "synthetic-private-text"})
    else:
        h.title_gateway.respond(
            json={
                "empty": {"content": ' " " '},
                "missing": {},
                "invalid_content": {"content": 1},
            }[failure]
        )
    response = await h.send(identifier)
    assert response.status_code == 200
    assert [event["type"] for event in events(response)] == ["delta", "completed"]
    assert h.store.rows[UUID(identifier)]["title"] == "Question"


@pytest.mark.parametrize(
    "failure", ["no_tiers", "rights_unavailable", "check_denied", "check_unavailable"]
)
async def test_title_rights_are_rechecked_fail_closed(h: Harness, failure: str) -> None:
    identifier = await h.conversation()
    if failure in {"no_tiers", "rights_unavailable"}:
        second = (
            httpx.Response(200, json={"chat_tiers": [], "skills": []})
            if failure == "no_tiers"
            else httpx.Response(503)
        )
        h.rights.mock(
            side_effect=[
                httpx.Response(200, json={"chat_tiers": [1], "skills": []}),
                second,
            ]
        )
    else:
        second = (
            httpx.Response(200, json={"allowed": False})
            if failure == "check_denied"
            else httpx.Response(503)
        )
        h.check.mock(side_effect=[httpx.Response(200, json={"allowed": True}), second])
    response = await h.send(identifier)
    assert response.status_code == 200
    assert events(response)[-1]["type"] == "completed"
    assert not h.title_gateway.called
    assert h.store.rows[UUID(identifier)]["title"] == "Question"


async def test_failed_and_tool_requested_answers_do_not_trigger_title(
    h: Harness,
) -> None:
    identifier = await h.conversation()
    h.gateway.respond(
        text=h.sse(
            [
                {"type": "delta", "text": "Partial"},
                {
                    "type": "failed",
                    "error": {"code": "unavailable", "message": "Failed"},
                },
            ]
        ),
        headers={"Content-Type": "text/event-stream"},
    )
    assert events(await h.send(identifier))[-1]["type"] == "failed"
    assert not h.title_gateway.called
    h.gateway.respond(
        text=h.sse(
            [
                {
                    "type": "tool_call",
                    "id": "tool-1",
                    "name": "slides",
                    "arguments": {},
                },
                h.completed(),
            ]
        ),
        headers={"Content-Type": "text/event-stream"},
    )
    assert events(await h.send(identifier))[-1]["type"] == "completed"
    assert not h.title_gateway.called
    h.gateway.respond(
        text=h.sse([{"type": "delta", "text": "First real answer"}, h.completed()]),
        headers={"Content-Type": "text/event-stream"},
    )
    h.title_gateway.respond(json={"content": "First successful answer title"})
    assert events(await h.send(identifier))[-1]["type"] == "title"
    assert h.title_gateway.call_count == 1
    assert (
        json.loads(h.title_gateway.calls.last.request.content)["messages"][1]["content"]
        == "Question"
    )


async def test_title_text_and_context_never_logged(
    h: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    identifier = await h.conversation()
    question = "synthetic-private-question"
    answer = "synthetic-private-answer"
    title = "synthetic-private-generated-title"
    h.gateway.respond(
        text=h.sse([{"type": "delta", "text": answer}, h.completed()]),
        headers={"Content-Type": "text/event-stream"},
    )
    h.title_gateway.respond(json={"content": title})
    await h.send(identifier, content=question)
    rendered = "\n".join(JsonFormatter().format(record) for record in caplog.records)
    for value in (question, answer, title, TITLE_PROMPT):
        assert value not in rendered
        assert value not in caplog.text
