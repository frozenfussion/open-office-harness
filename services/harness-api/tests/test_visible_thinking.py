# SPDX-License-Identifier: AGPL-3.0-only
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
import pytest
from conftest import Harness
from starlette.requests import ClientDisconnect
from test_routes import events

from harness_api.diagnostics import JsonFormatter

pytestmark = pytest.mark.anyio


async def test_thinking_interleaves_with_answer_and_is_stored_separately(
    h: Harness,
) -> None:
    identifier = await h.conversation()
    h.gateway.respond(
        text=h.sse(
            [
                {"type": "thinking", "text": "First thought. "},
                {"type": "delta", "text": "Answer"},
                {"type": "thinking", "text": "Second thought."},
                h.completed(),
            ]
        ),
        headers={"Content-Type": "text/event-stream"},
    )
    response = await h.send(identifier)
    result = events(response)
    assert [event["type"] for event in result] == [
        "thinking",
        "delta",
        "thinking",
        "completed",
    ]
    assert result[0] == {"type": "thinking", "text": "First thought. "}
    assert result[-1]["usage"] == {"input_tokens": 4, "output_tokens": 2}
    row = (await h.client.get(f"/api/conversations/{identifier}")).json()
    assert row["messages"][0]["thinking"] is None
    assistant = row["messages"][-1]
    assert assistant["content"] == "Answer"
    assert assistant["thinking"] == "First thought. Second thought."
    assert assistant["outcome"] == "completed"


async def test_thinking_is_never_logged_or_sent_back_to_any_model(
    h: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    caplog.set_level(logging.DEBUG)
    first = "PRIVATE_THINKING_CHUNK_A_29c7"
    second = "PRIVATE_THINKING_CHUNK_B_58e3"
    identifier = await h.conversation()
    h.gateway.respond(
        text=h.sse(
            [
                {"type": "thinking", "text": first},
                {"type": "delta", "text": "Answer"},
                {"type": "thinking", "text": second},
                h.completed(),
            ]
        ),
        headers={"Content-Type": "text/event-stream"},
    )
    h.title_gateway.respond(json={"content": "A useful short title"})
    await h.send(identifier)
    await h.send(identifier, content="Next question")
    assert h.store.rows[UUID(identifier)]["messages"][1]["thinking"] == first + second
    for call in [*h.gateway.calls, *h.title_gateway.calls]:
        body = json.loads(call.request.content)
        assert all(set(message) == {"role", "content"} for message in body["messages"])
        assert first not in call.request.content.decode()
        assert second not in call.request.content.decode()
    assert caplog.records
    for record in caplog.records:
        for text in (first, second, first + second):
            assert text not in repr(record.__dict__)
            assert text not in JsonFormatter().format(record)
    assert first not in caplog.text and second not in caplog.text


class ThinkingBreak(httpx.AsyncByteStream):
    def __init__(self, answer: bool) -> None:
        self.answer = answer

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'data: {"type":"thinking","text":"PRIVATE_PARTIAL_THINKING"}\n\n'
        if self.answer:
            yield b'data: {"type":"delta","text":"Partial answer"}\n\n'
        raise httpx.ReadError("Synthetic stream failure")


@pytest.mark.parametrize("answer", [False, True])
async def test_failed_stream_keeps_partial_thinking(
    h: Harness, answer: bool, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    caplog.set_level(logging.DEBUG)
    identifier = await h.conversation()
    h.gateway.respond(
        stream=ThinkingBreak(answer), headers={"Content-Type": "text/event-stream"}
    )
    result = events(await h.send(identifier))
    assert result[0]["type"] == "thinking"
    assert result[-1]["type"] == "failed"
    assistant = h.store.rows[UUID(identifier)]["messages"][-1]
    assert assistant["thinking"] == "PRIVATE_PARTIAL_THINKING"
    assert assistant["content"] == ("Partial answer" if answer else "")
    assert assistant["outcome"] == "failed"
    assert not h.title_gateway.called
    assert "PRIVATE_PARTIAL_THINKING" not in caplog.text
    for record in caplog.records:
        assert "PRIVATE_PARTIAL_THINKING" not in repr(record.__dict__)
        assert "PRIVATE_PARTIAL_THINKING" not in JsonFormatter().format(record)


async def test_disconnect_after_thinking_preserves_it(h: Harness) -> None:
    identifier = await h.conversation()
    h.gateway.respond(
        text=h.sse([{"type": "thinking", "text": "Partial thinking"}, h.completed()]),
        headers={"Content-Type": "text/event-stream"},
    )
    received = False

    async def receive() -> dict[str, Any]:
        nonlocal received
        assert not received
        received = True
        return {
            "type": "http.request",
            "body": b'{"content":"Question"}',
            "more_body": False,
        }

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.body":
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
    assistant = h.store.rows[UUID(identifier)]["messages"][-1]
    assert assistant["thinking"] == "Partial thinking"
    assert assistant["outcome"] == "failed" and assistant["content"] == ""


async def test_absent_or_empty_thinking_is_null_in_history(h: Harness) -> None:
    identifier = await h.conversation()
    h.gateway.respond(
        text=h.sse(
            [
                {"type": "thinking", "text": ""},
                {"type": "delta", "text": "Answer"},
                h.completed(),
            ]
        ),
        headers={"Content-Type": "text/event-stream"},
    )
    result = events(await h.send(identifier))
    assert [event["type"] for event in result] == ["delta", "completed"]
    assert h.store.rows[UUID(identifier)]["messages"][-1]["thinking"] is None


async def test_empty_thinking_does_not_start_browser_stream(h: Harness) -> None:
    identifier = await h.conversation()
    h.gateway.respond(
        text=h.sse(
            [
                {"type": "thinking", "text": ""},
                {
                    "type": "failed",
                    "error": {"code": "no_model", "message": "No model"},
                },
            ]
        ),
        headers={"Content-Type": "text/event-stream"},
    )
    response = await h.send(identifier)
    assert response.status_code == 503 and response.json()["code"] == "no_model"


@pytest.mark.parametrize("text", [None, 3, []])
async def test_invalid_thinking_text_is_an_unexpected_answer(
    h: Harness, text: Any
) -> None:
    identifier = await h.conversation()
    h.gateway.respond(
        text=h.sse([{"type": "thinking", "text": text}]),
        headers={"Content-Type": "text/event-stream"},
    )
    response = await h.send(identifier)
    assert response.status_code == 503 and response.json()["code"] == "unavailable"


async def test_thinking_extra_fields_are_not_forwarded(h: Harness) -> None:
    identifier = await h.conversation()
    h.gateway.respond(
        text=h.sse(
            [
                {
                    "type": "thinking",
                    "text": "Visible summary",
                    "signature": "PRIVATE_SIGNATURE",
                    "encrypted_reasoning": "PRIVATE_CIPHERTEXT",
                },
                h.completed(),
            ]
        ),
        headers={"Content-Type": "text/event-stream"},
    )
    response = await h.send(identifier)
    assert events(response)[0] == {"type": "thinking", "text": "Visible summary"}
    assert (
        "PRIVATE_SIGNATURE" not in response.text
        and "PRIVATE_CIPHERTEXT" not in response.text
    )


async def test_thinking_is_not_forwarded_after_completed(h: Harness) -> None:
    identifier = await h.conversation()
    h.gateway.respond(
        text=h.sse([h.completed(), {"type": "thinking", "text": "Late thinking"}]),
        headers={"Content-Type": "text/event-stream"},
    )
    assert [event["type"] for event in events(await h.send(identifier))] == [
        "completed"
    ]
    assert h.store.rows[UUID(identifier)]["messages"][-1]["thinking"] is None


@pytest.mark.parametrize("failed", [False, True])
async def test_thinking_storage_cap_does_not_cap_stream(
    h: Harness, failed: bool
) -> None:
    identifier = await h.conversation()
    chunks = ["界" * 99_999, "🙂tail-after-cap", "more-after-cap"]
    ending = (
        {"type": "failed", "error": {"code": "unavailable", "message": "Failed"}}
        if failed
        else h.completed()
    )
    h.gateway.respond(
        text=h.sse(
            [
                *({"type": "thinking", "text": chunk} for chunk in chunks),
                {"type": "delta", "text": "Answer"},
                ending,
            ]
        ),
        headers={"Content-Type": "text/event-stream"},
    )
    result = events(await h.send(identifier))
    assert [event["text"] for event in result if event["type"] == "thinking"] == chunks
    assistant = h.store.rows[UUID(identifier)]["messages"][-1]
    assert assistant["thinking"] == "界" * 99_999 + "🙂"
    assert len(assistant["thinking"]) == 100_000
    assert assistant["outcome"] == ("failed" if failed else "completed")


async def test_unknown_events_are_ignored_before_and_between_known_events(
    h: Harness,
) -> None:
    identifier = await h.conversation()
    h.gateway.respond(
        text=h.sse(
            [
                {"type": "future-event", "text": "PRIVATE_FUTURE_PAYLOAD"},
                {"type": "thinking", "text": "Visible thinking"},
                {
                    "type": "future-version",
                    "new_field": {"private": "PRIVATE_FUTURE_PAYLOAD"},
                },
                {"type": "delta", "text": "Answer"},
                h.completed(),
            ]
        ),
        headers={"Content-Type": "text/event-stream"},
    )
    response = await h.send(identifier)
    assert [event["type"] for event in events(response)] == [
        "thinking",
        "delta",
        "completed",
    ]
    assert "PRIVATE_FUTURE_PAYLOAD" not in response.text
    assert (
        h.store.rows[UUID(identifier)]["messages"][-1]["thinking"] == "Visible thinking"
    )


async def test_unknown_event_does_not_start_the_browser_stream(h: Harness) -> None:
    identifier = await h.conversation()
    h.gateway.respond(
        text=h.sse(
            [
                {"type": "future-event", "text": "Ignored"},
                {
                    "type": "failed",
                    "error": {"code": "no_model", "message": "No model"},
                },
            ]
        ),
        headers={"Content-Type": "text/event-stream"},
    )
    response = await h.send(identifier)
    assert response.status_code == 503 and response.json()["code"] == "no_model"


@pytest.mark.parametrize("code", ["unavailable", "budget_exceeded"])
async def test_failure_after_thinking_never_calls_another_tier(
    h: Harness, code: str
) -> None:
    identifier = await h.conversation()
    h.gateway.respond(
        text=h.sse(
            [
                {"type": "thinking", "text": "Partial thinking"},
                {"type": "failed", "error": {"code": code, "message": "Failed"}},
            ]
        ),
        headers={"Content-Type": "text/event-stream"},
    )
    response = await h.send(identifier)
    assert [event["type"] for event in events(response)] == ["thinking", "failed"]
    assert h.gateway.call_count == 1 and not h.title_gateway.called
    assert (
        h.store.rows[UUID(identifier)]["messages"][-1]["thinking"] == "Partial thinking"
    )


async def test_malformed_thinking_has_a_sanitized_exception_message(h: Harness) -> None:
    private = "PRIVATE_MALFORMED_THINKING"
    h.gateway.respond(
        text=h.sse([{"type": "thinking", "text": {"private": private}}]),
        headers={"Content-Type": "text/event-stream"},
    )
    stream = await h.app.state.upstream.open(
        "test-user", 1, [{"role": "user", "content": "Question"}], []
    )
    try:
        with pytest.raises(ValueError) as error:
            await anext(stream.events)
        assert str(error.value) == "Unexpected Gateway event"
        assert private not in str(error.value)
    finally:
        await stream.close()
