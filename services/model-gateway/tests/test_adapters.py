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


@pytest.mark.parametrize(
    "text,key,expected",
    [
        (
            "full abcdefghijklmnop; partial defghijkl; end",
            "abcdefghijklmnop",
            "full [removed]; partial [removed]; end",
        ),
        (
            "partial abcdefgh and ijklmnop",
            "abcdefghijklmnop",
            "partial [removed] and [removed]",
        ),
        (
            "small abc; sk-other_secret; sk-ant-other_secret",
            "abc",
            "small [removed]; [removed]; [removed]",
        ),
        ("no saved key sk-another_secret", "", "no saved key [removed]"),
        ("key-less text", "", "key-less text"),
    ],
)
def test_provider_message_redaction(text: str, key: str, expected: str) -> None:
    from gateway.adapters.common import sanitize_message

    assert sanitize_message(text, key) == expected


@pytest.mark.anyio
async def test_provider_error_body_read_is_bounded(entry: Entry, call: Call) -> None:
    from collections.abc import AsyncIterator

    from gateway.adapters.common import ProviderError

    class Body(httpx.AsyncByteStream):
        reads = 0
        closed = False

        async def __aiter__(self) -> AsyncIterator[bytes]:
            self.reads += 1
            yield b"x" * 4096
            self.reads += 1
            yield b"must not read this" * 4096

        async def aclose(self) -> None:
            self.closed = True

    body = Body()
    with respx.mock as mock:
        mock.post("https://example.invalid/chat/completions").mock(
            return_value=httpx.Response(500, stream=body)
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(ProviderError) as error:
                _ = [
                    event
                    async for event in resolve(entry)(client, entry, "fake-key", call)
                ]
    assert body.reads == 1 and body.closed
    assert error.value.status == 500 and error.value.provider_message == "x" * 300


@pytest.mark.anyio
@pytest.mark.parametrize("kind", TYPES)
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "thinking,off_settings",
    [
        (True, {"extra": "off", "remove_me": None, "nested": {"mode": "off"}}),
        (False, {"extra": "off", "remove_me": None, "nested": {"mode": "off"}}),
        (False, None),
        (False, {}),
    ],
)
async def test_thinking_off_settings_merge_last(
    entry: Entry,
    call: Call,
    kind: str,
    stream: bool,
    thinking: bool,
    off_settings: dict | None,
) -> None:
    normal = {
        "extra": "normal",
        "remove_me": "normal",
        "nested": {"keep": "normal"},
        "normal_only": "kept",
    }
    entry = entry.model_copy(
        update={
            "api_type": kind,
            "request_settings": normal,
            "request_settings_thinking_off": off_settings,
        }
    )
    call = call.model_copy(update={"stream": stream, "thinking": thinking})
    response = (
        httpx.Response(
            200,
            text="".join(
                "data: " + json.dumps(value) + "\n\n" for value in chunks(kind)
            ),
        )
        if stream
        else httpx.Response(200, json=answer(kind))
    )
    with respx.mock as mock:
        route = mock.post(url__startswith="https://example.invalid/").mock(
            return_value=response
        )
        async with httpx.AsyncClient() as client:
            _ = [
                event async for event in resolve(entry)(client, entry, "fake-key", call)
            ]
        body = json.loads(route.calls[0].request.content)
    assert body["normal_only"] == "kept"
    if not thinking and off_settings:
        assert body["extra"] == "off" and "remove_me" not in body
        assert body["nested"] == {"mode": "off"}
    else:
        assert body["extra"] == "normal" and body["remove_me"] == "normal"
        assert body["nested"] == {"keep": "normal"}
    assert "thinking" not in body
    assert entry.request_settings == normal


def test_thinking_defaults_true_and_registry_off_settings_are_objects(
    entry: Entry, call: Call
) -> None:
    from pydantic import ValidationError

    assert Call.model_validate(call.model_dump(exclude={"thinking"})).thinking is True
    assert (
        Entry.model_validate(
            entry.model_dump(by_alias=True, exclude={"request_settings_thinking_off"})
        ).request_settings_thinking_off
        is None
    )
    for invalid in ([], "fake", 1, False):
        with pytest.raises(ValidationError):
            Entry.model_validate(
                entry.model_dump(by_alias=True)
                | {"request_settings_thinking_off": invalid}
            )


def thinking_chunks(kind: str) -> list[dict]:
    if kind == "openai_chat_completions":
        return [
            {
                "choices": [
                    {
                        "delta": {
                            "reasoning_content": "",
                            "signature": "private-signature",
                        }
                    }
                ]
            },
            {"choices": [{"delta": {"reasoning_content": "Consider "}}]},
            {
                "choices": [
                    {
                        "delta": {
                            "content": "Hello ",
                            "encrypted_reasoning": "private-encrypted",
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {"reasoning_content": "this", "content": "world"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 3},
            },
        ]
    if kind == "openai_responses":
        return [
            {"type": "future.event", "text": "private-unknown"},
            {"type": "response.reasoning_text.delta", "delta": "private-raw"},
            {
                "type": "response.output_item.added",
                "item": {
                    "type": "reasoning",
                    "encrypted_content": "private-encrypted",
                    "summary": [{"text": "private-not-delta"}],
                },
            },
            {"type": "response.reasoning_summary_text.delta", "delta": ""},
            {"type": "response.reasoning_summary_text.delta", "delta": "Consider "},
            {"type": "response.output_text.delta", "delta": "Hello "},
            {"type": "response.reasoning_summary_text.done", "text": "private-done"},
            {"type": "response.reasoning_summary_text.delta", "delta": "this"},
            {"type": "response.output_text.delta", "delta": "world"},
            {
                "type": "response.completed",
                "response": {"usage": {"input_tokens": 8, "output_tokens": 3}},
            },
            {"type": "response.reasoning_summary_text.delta", "delta": "private-late"},
        ]
    return [
        {"type": "message_start", "message": {"usage": {"input_tokens": 8}}},
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "thinking",
                "thinking": "",
                "signature": "private-signature",
            },
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "Consider "},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "signature_delta", "signature": "private-signature"},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "text_delta", "text": "Hello "},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "this"},
        },
        {
            "type": "content_block_start",
            "index": 2,
            "content_block": {
                "type": "redacted_thinking",
                "data": "private-redacted",
                "thinking": "private-redacted",
            },
        },
        {
            "type": "content_block_delta",
            "index": 2,
            "delta": {"type": "thinking_delta", "thinking": "private-redacted"},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "text_delta", "text": "world"},
        },
        {"type": "message_delta", "usage": {"output_tokens": 3}},
        {"type": "message_stop"},
    ]


def thinking_answer(kind: str) -> dict:
    if kind == "openai_chat_completions":
        return {
            "choices": [
                {
                    "message": {
                        "content": "Hello world",
                        "reasoning_content": "Consider this",
                        "signature": "private-signature",
                        "encrypted_reasoning": "private-encrypted",
                    }
                }
            ],
            "usage": {"prompt_tokens": 8, "completion_tokens": 3},
        }
    if kind == "openai_responses":
        return {
            "output": [
                {
                    "type": "reasoning",
                    "summary": [
                        {"text": "Consider "},
                        {"text": ""},
                        {"text": {"data": "private-object"}},
                        {"text": "this"},
                    ],
                    "encrypted_content": "private-encrypted",
                },
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Hello world"}],
                },
            ],
            "usage": {"input_tokens": 8, "output_tokens": 3},
        }
    return {
        "content": [
            {"type": "thinking", "thinking": "", "signature": "private-signature"},
            {
                "type": "thinking",
                "thinking": "Consider ",
                "signature": "private-signature",
            },
            {"type": "text", "text": "Hello "},
            {
                "type": "redacted_thinking",
                "data": "private-redacted",
                "thinking": "private-redacted",
            },
            {"type": "thinking", "thinking": "this", "signature": "private-signature"},
            {"type": "text", "text": "world"},
        ],
        "usage": {"input_tokens": 8, "output_tokens": 3},
    }


@pytest.mark.anyio
@pytest.mark.parametrize("kind", TYPES)
@pytest.mark.parametrize("stream", [False, True])
async def test_visible_thinking_events_and_private_blocks(
    entry: Entry, call: Call, kind: str, stream: bool
) -> None:
    entry = entry.model_copy(
        update={
            "api_type": kind,
            "request_settings": {
                "thinking": {"type": "enabled", "display": "summarized"},
                "reasoning": {"summary": "auto"},
            },
        }
    )
    call = call.model_copy(update={"stream": stream})
    response = (
        httpx.Response(
            200,
            text="".join(
                "data: " + json.dumps(event) + "\n\n" for event in thinking_chunks(kind)
            ),
        )
        if stream
        else httpx.Response(200, json=thinking_answer(kind))
    )
    with respx.mock as mock:
        route = mock.post(url__startswith="https://example.invalid/").mock(
            return_value=response
        )
        async with httpx.AsyncClient() as client:
            events = [
                event async for event in resolve(entry)(client, entry, "fake-key", call)
            ]
        body = json.loads(route.calls[0].request.content)
        assert body["thinking"] == {"type": "enabled", "display": "summarized"}
        assert body["reasoning"] == {"summary": "auto"}
    assert "".join(
        event["text"] for event in events if event["type"] == "thinking"
    ) == (
        "Consider \n\nthis"
        if not stream and kind != "openai_chat_completions"
        else "Consider this"
    )
    assert (
        "".join(event["text"] for event in events if event["type"] == "delta")
        == "Hello world"
    )
    assert events[-1] == {"type": "usage", "input_tokens": 8, "output_tokens": 3}
    assert all(event.get("text") != "" for event in events)
    assert "private-" not in json.dumps(events)
    if stream:
        assert [event["type"] for event in events] == [
            "thinking",
            "delta",
            "thinking",
            "delta",
            "usage",
        ]


@pytest.mark.anyio
@pytest.mark.parametrize("stream", [False, True])
async def test_responses_without_summary_setting_suppresses_reasoning(
    entry: Entry, call: Call, stream: bool
) -> None:
    entry = entry.model_copy(update={"api_type": "openai_responses"})
    call = call.model_copy(update={"stream": stream})
    if stream:
        values = [
            {
                "type": "response.reasoning_summary_text.delta",
                "delta": "private-summary",
            },
            {
                "type": "response.output_item.added",
                "item": {"type": "reasoning", "encrypted_content": "private-encrypted"},
            },
            *chunks("openai_responses"),
        ]
        response = httpx.Response(
            200, text="".join("data: " + json.dumps(event) + "\n\n" for event in values)
        )
    else:
        value = answer("openai_responses")
        value["output"].insert(
            0,
            {
                "type": "reasoning",
                "summary": [{"text": "private-summary"}],
                "encrypted_content": "private-encrypted",
            },
        )
        response = httpx.Response(200, json=value)
    with respx.mock as mock:
        mock.post("https://example.invalid/responses").mock(return_value=response)
        async with httpx.AsyncClient() as client:
            events = [
                event async for event in resolve(entry)(client, entry, "fake-key", call)
            ]
    assert not [event for event in events if event["type"] == "thinking"]
    assert "private-" not in json.dumps(events)


@pytest.mark.anyio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "fields,expected",
    [
        ({"reasoning": "Consider this"}, "Consider this"),
        (
            {"reasoning_content": "Consider this", "reasoning": "private-alternate"},
            "Consider this",
        ),
        ({"reasoning_content": "", "reasoning": "Consider this"}, "Consider this"),
        (
            {
                "reasoning_content": {"data": "private-object"},
                "reasoning": "Consider this",
            },
            "Consider this",
        ),
        (
            {
                "reasoning": {"data": "private-object"},
                "reasoning_details": [{"text": "private-details"}],
            },
            None,
        ),
        ({"reasoning_content": {"data": "private-object"}, "reasoning": None}, None),
    ],
)
async def test_chat_reasoning_names_and_string_only_forms(
    entry: Entry, call: Call, stream: bool, fields: dict, expected: str | None
) -> None:
    call = call.model_copy(update={"stream": stream})
    if stream:
        response = httpx.Response(
            200,
            text="data: "
            + json.dumps(
                {
                    "choices": [
                        {
                            "delta": fields | {"content": "Hello world"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 8, "completion_tokens": 3},
                }
            )
            + "\n\n",
        )
    else:
        response = httpx.Response(
            200,
            json={
                "choices": [{"message": fields | {"content": "Hello world"}}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 3},
            },
        )
    with respx.mock as mock:
        mock.post("https://example.invalid/chat/completions").mock(
            return_value=response
        )
        async with httpx.AsyncClient() as client:
            events = [
                event async for event in resolve(entry)(client, entry, "fake-key", call)
            ]
    thinking = [event["text"] for event in events if event["type"] == "thinking"]
    assert thinking == ([expected] if expected else [])
    assert "private-" not in json.dumps(events)


@pytest.mark.anyio
@pytest.mark.parametrize("kind", TYPES)
async def test_unknown_provider_events_are_ignored(
    entry: Entry, call: Call, kind: str
) -> None:
    entry = entry.model_copy(update={"api_type": kind})
    events = [{"type": "future.event", "text": "private-unknown"}, *chunks(kind)]
    with respx.mock as mock:
        mock.post(url__startswith="https://example.invalid/").mock(
            return_value=httpx.Response(
                200,
                text="".join("data: " + json.dumps(event) + "\n\n" for event in events),
            )
        )
        async with httpx.AsyncClient() as client:
            result = [
                event async for event in resolve(entry)(client, entry, "fake-key", call)
            ]
    assert "private-unknown" not in json.dumps(result)
    assert (
        "".join(event["text"] for event in result if event["type"] == "delta")
        == "Hello world"
    )
    assert result[-1] == {"type": "usage", "input_tokens": 8, "output_tokens": 3}


@pytest.mark.anyio
@pytest.mark.parametrize("stream", [False, True])
async def test_responses_summary_uses_effective_request_settings(
    entry: Entry, call: Call, stream: bool
) -> None:
    entry = entry.model_copy(
        update={
            "api_type": "openai_responses",
            "request_settings": {"reasoning": {"summary": "auto"}},
            "request_settings_thinking_off": {"reasoning": {"effort": "low"}},
        }
    )
    call = call.model_copy(update={"stream": stream, "thinking": False})
    response = (
        httpx.Response(
            200,
            text="".join(
                "data: " + json.dumps(event) + "\n\n"
                for event in thinking_chunks("openai_responses")
            ),
        )
        if stream
        else httpx.Response(200, json=thinking_answer("openai_responses"))
    )
    with respx.mock as mock:
        route = mock.post("https://example.invalid/responses").mock(
            return_value=response
        )
        async with httpx.AsyncClient() as client:
            result = [
                event async for event in resolve(entry)(client, entry, "fake-key", call)
            ]
        assert json.loads(route.calls[0].request.content)["reasoning"] == {
            "effort": "low"
        }
    assert not [event for event in result if event["type"] == "thinking"]
    assert "private-" not in json.dumps(result)
