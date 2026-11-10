# SPDX-License-Identifier: AGPL-3.0-only
import json

import httpx
import pytest
import respx

from gateway.adapters import resolve
from gateway.models import Call, Entry

TYPES = ["openai_chat_completions", "openai_responses", "anthropic_messages"]


def chunks(kind: str) -> list[dict]:
    if kind == TYPES[0]:
        return [
            {"choices": [{"delta": {"content": "Hello "}}]},
            {
                "choices": [
                    {
                        "delta": {
                            "content": "world",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_",
                                    "function": {"name": "fake_", "arguments": '{"x":'},
                                }
                            ],
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "one",
                                    "function": {"name": "tool", "arguments": "1}"},
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 2},
            },
            {"choices": [], "usage": {"prompt_tokens": 8, "completion_tokens": 3}},
            {"choices": [], "usage": None},
        ]
    if kind == TYPES[1]:
        return [
            {"type": "response.output_text.delta", "delta": "Hello "},
            {"type": "response.output_text.delta", "delta": "world"},
            {
                "type": "response.output_item.added",
                "item": {
                    "type": "function_call",
                    "id": "item1",
                    "call_id": "call_one",
                    "name": "fake_tool",
                },
            },
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "item1",
                "delta": '{"x":',
            },
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "item1",
                "delta": "1}",
            },
            {
                "type": "response.function_call_arguments.done",
                "item_id": "item1",
                "arguments": '{"x":1}',
            },
            {
                "type": "response.completed",
                "response": {"usage": {"input_tokens": 8, "output_tokens": 3}},
            },
        ]
    return [
        {"type": "ping"},
        {"type": "future_event"},
        {"type": "message_start", "message": {"usage": {"input_tokens": 8}}},
        {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "Hello "},
        },
        {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "world"},
        },
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {
                "type": "tool_use",
                "id": "call_one",
                "name": "fake_tool",
                "input": {},
            },
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"x":'},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": "1}"},
        },
        {"type": "message_delta", "usage": {"output_tokens": 1}},
        {"type": "message_delta", "usage": {"output_tokens": 3}},
        {"type": "message_stop"},
    ]


def answer(kind: str) -> dict:
    if kind == TYPES[0]:
        return {
            "choices": [
                {
                    "message": {
                        "content": "Hello world",
                        "tool_calls": [
                            {
                                "id": "call_one",
                                "function": {
                                    "name": "fake_tool",
                                    "arguments": '{"x":1}',
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 8, "completion_tokens": 3},
        }
    if kind == TYPES[1]:
        return {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Hello world"}],
                },
                {
                    "type": "function_call",
                    "call_id": "call_one",
                    "name": "fake_tool",
                    "arguments": '{"x":1}',
                },
            ],
            "usage": {"input_tokens": 8, "output_tokens": 3},
        }
    return {
        "content": [
            {"type": "text", "text": "Hello world"},
            {
                "type": "tool_use",
                "id": "call_one",
                "name": "fake_tool",
                "input": {"x": 1},
            },
        ],
        "usage": {"input_tokens": 8, "output_tokens": 3},
    }


@pytest.mark.anyio
@pytest.mark.parametrize("kind", TYPES)
@pytest.mark.parametrize("stream", [False, True])
async def test_adapter_requests_and_answers(
    entry: Entry, call: Call, kind: str, stream: bool
) -> None:
    entry = entry.model_copy(update={"api_type": kind})
    call = call.model_copy(update={"stream": stream})
    payload = "".join("data: " + json.dumps(value) + "\n\n" for value in chunks(kind))
    response = (
        httpx.Response(200, text=payload)
        if stream
        else httpx.Response(200, json=answer(kind))
    )
    with respx.mock as mock:
        route = mock.post(url__startswith="https://example.invalid/").mock(
            return_value=response
        )
        async with httpx.AsyncClient() as client:
            events = [
                event async for event in resolve(entry)(client, entry, "fake-key", call)
            ]
        request = route.calls[0].request
        body = json.loads(request.content)
        assert body["model"] == "fake-model" and body["stream"] == stream
        assert body["tools"]
        if kind == TYPES[0]:
            assert request.url.path == "/chat/completions"
            assert body["tools"][0]["function"]["parameters"] == {"type": "object"}
            assert "max_tokens" not in body and "max_completion_tokens" not in body
            if stream:
                assert body["stream_options"] == {"include_usage": True}
        elif kind == TYPES[1]:
            assert request.url.path == "/responses"
            assert body["store"] is False and body["instructions"] == "Fake instruction"
            assert body["tools"][0]["strict"] is False
            assert "max_output_tokens" not in body
        else:
            assert request.url.path == "/v1/messages"
            assert request.headers["x-api-key"] == "fake-key"
            assert request.headers["anthropic-version"] == "2023-06-01"
            assert body["system"] == "Fake instruction" and body["max_tokens"] == 4096
        if kind != TYPES[2]:
            assert request.headers["Authorization"] == "Bearer fake-key"
        assert (
            "".join(e["text"] for e in events if e["type"] == "delta") == "Hello world"
        )
        assert {
            "type": "tool_call",
            "id": "call_one",
            "name": "fake_tool",
            "arguments": {"x": 1},
        } in events
        assert events[-1] == {"type": "usage", "input_tokens": 8, "output_tokens": 3}


@pytest.mark.anyio
@pytest.mark.parametrize("kind", TYPES)
async def test_settings_merge_and_null_removal(
    entry: Entry, call: Call, kind: str
) -> None:
    entry = entry.model_copy(
        update={
            "api_type": kind,
            "request_settings": {"tools": None, "extra": "fake", "max_tokens": 51},
        }
    )
    call = call.model_copy(update={"stream": False})
    with respx.mock as mock:
        route = mock.post(url__startswith="https://example.invalid/").mock(
            return_value=httpx.Response(200, json=answer(kind))
        )
        async with httpx.AsyncClient() as client:
            _ = [e async for e in resolve(entry)(client, entry, "fake-key", call)]
        body = json.loads(route.calls[0].request.content)
        assert (
            "tools" not in body and body["extra"] == "fake" and body["max_tokens"] == 51
        )


@pytest.mark.anyio
@pytest.mark.parametrize("kind", TYPES)
async def test_truncated_stream_fails(entry: Entry, call: Call, kind: str) -> None:
    entry = entry.model_copy(update={"api_type": kind})
    with respx.mock as mock:
        mock.post(url__startswith="https://example.invalid/").mock(
            return_value=httpx.Response(200, text='data: {"choices":[]}\n\n')
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(RuntimeError):
                _ = [e async for e in resolve(entry)(client, entry, "fake-key", call)]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "kind,event",
    [
        (TYPES[1], "response.failed"),
        (TYPES[1], "response.incomplete"),
        (TYPES[1], "error"),
        (TYPES[2], "error"),
    ],
)
async def test_error_events_fail(
    entry: Entry, call: Call, kind: str, event: str
) -> None:
    entry = entry.model_copy(update={"api_type": kind})
    with respx.mock as mock:
        mock.post(url__startswith="https://example.invalid/").mock(
            return_value=httpx.Response(
                200, text="data: " + json.dumps({"type": event}) + "\n\n"
            )
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(RuntimeError):
                _ = [e async for e in resolve(entry)(client, entry, "fake-key", call)]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "message", [{}, {"usage": {}}, {"usage": {"output_tokens": 0}}]
)
async def test_messages_missing_input_usage_defaults_zero(
    entry: Entry, call: Call, message: dict
) -> None:
    entry = entry.model_copy(update={"api_type": "anthropic_messages"})
    events = chunks("anthropic_messages")
    events[2] = {"type": "message_start", "message": message}
    payload = "".join("data: " + json.dumps(event) + "\n\n" for event in events)
    with respx.mock as mock:
        mock.post("https://example.invalid/v1/messages").mock(
            return_value=httpx.Response(200, text=payload)
        )
        async with httpx.AsyncClient() as client:
            result = [
                event async for event in resolve(entry)(client, entry, "fake-key", call)
            ]
    assert result[0] == {"type": "delta", "text": "Hello "}
    assert result[-1] == {"type": "usage", "input_tokens": 0, "output_tokens": 3}
