# SPDX-License-Identifier: AGPL-3.0-only
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from gateway.models import Call, Entry

from .common import (
    ProviderError,
    check_response,
    forced_choice,
    matching_state,
    request_body,
    sse,
    state_event,
    tool_event,
)


def messages(call: Call, entry: Entry) -> list[dict[str, Any]]:
    result = []
    for message in call.messages:
        if message.role == "system":
            continue
        if message.role == "tool":
            item = {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": message.tool_call_id,
                        "content": message.content,
                    }
                ],
            }
            if (
                result
                and result[-1]["role"] == "user"
                and isinstance(result[-1]["content"], list)
            ):
                result[-1]["content"].extend(item["content"])
                continue
        elif message.role == "assistant":
            blocks = matching_state(message, entry).get("content")
            if blocks is None:
                blocks = (
                    [{"type": "text", "text": message.content}]
                    if message.content
                    else []
                ) + [
                    {
                        "type": "tool_use",
                        "id": t.id,
                        "name": t.name,
                        "input": t.arguments,
                    }
                    for t in message.tool_calls
                ]
            item = {"role": "assistant", "content": blocks}
        else:
            item = {"role": message.role, "content": message.content}
        result.append(item)
    return result


async def run(
    client: httpx.AsyncClient,
    entry: Entry,
    key: str,
    call: Call,
    *,
    auto_tool_choice: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    body = {
        "model": entry.model_id,
        "messages": messages(call, entry),
        "max_tokens": 4096,
        "stream": call.stream,
    }
    system = "\n".join(m.content for m in call.messages if m.role == "system")
    if system:
        body["system"] = system
    if call.tools:
        body["tools"] = [t.model_dump() for t in call.tools]
    body = request_body(body, entry, call)
    yield {
        "type": "tool_choice_applied",
        "applied": forced_choice(body, call, entry.api_type, auto=auto_tool_choice),
    }
    async with client.stream(
        "POST",
        entry.endpoint_url.rstrip("/") + "/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        json=body,
        timeout=entry.timeout_seconds,
    ) as response:
        await check_response(response, key)
        if not call.stream:
            result = json.loads(await response.aread())
            thinking_seen = False
            for block in result["content"]:
                if block["type"] == "thinking" and block.get("thinking"):
                    if thinking_seen:
                        yield {"type": "thinking", "text": "\n\n"}
                    yield {"type": "thinking", "text": block["thinking"]}
                    thinking_seen = True
                elif block["type"] == "text" and block["text"]:
                    yield {"type": "delta", "text": block["text"]}
                elif block["type"] == "tool_use":
                    yield tool_event(
                        {
                            "id": block["id"],
                            "name": block["name"],
                            "arguments": block["input"],
                        }
                    )
            yield state_event(entry, content=result["content"])
            yield {
                "type": "usage",
                **{
                    k: result.get("usage", {}).get(k, 0)
                    for k in ("input_tokens", "output_tokens")
                },
            }
            return
        tools: dict[int, dict[str, Any]] = {}
        blocks: dict[int, dict[str, Any]] = {}
        redacted_indexes: set[int] = set()
        thinking_seen = False
        new_block = False
        usage = {"input_tokens": 0, "output_tokens": 0}
        async for event in sse(response):
            kind = event.get("type")
            if kind == "error":
                raise ProviderError()
            if kind == "message_start":
                usage["input_tokens"] = (
                    event.get("message", {}).get("usage", {}).get("input_tokens", 0)
                )
            elif kind == "content_block_start":
                block = dict(event["content_block"])
                blocks[event["index"]] = block
                if block["type"] == "redacted_thinking":
                    redacted_indexes.add(event["index"])
                elif block["type"] == "thinking":
                    new_block = thinking_seen
                    if block.get("thinking"):
                        if new_block:
                            yield {"type": "thinking", "text": "\n\n"}
                        yield {"type": "thinking", "text": block["thinking"]}
                        thinking_seen = True
                        new_block = False
                elif block["type"] == "tool_use":
                    tools[event["index"]] = {
                        "id": block["id"],
                        "name": block["name"],
                        "arguments": "",
                        "initial": block.get("input", {}),
                    }
            elif kind == "content_block_delta":
                delta = event["delta"]
                block = blocks.get(event.get("index"))
                if block is not None:
                    for dtype, field in [
                        ("thinking_delta", "thinking"),
                        ("signature_delta", "signature"),
                        ("text_delta", "text"),
                    ]:
                        if delta["type"] == dtype:
                            block[field] = block.get(field, "") + delta[field]
                if (
                    delta["type"] == "thinking_delta"
                    and event.get("index") not in redacted_indexes
                    and delta.get("thinking")
                ):
                    if new_block:
                        yield {"type": "thinking", "text": "\n\n"}
                    yield {"type": "thinking", "text": delta["thinking"]}
                    thinking_seen = True
                    new_block = False
                elif delta["type"] == "text_delta" and delta["text"]:
                    yield {"type": "delta", "text": delta["text"]}
                elif delta["type"] == "input_json_delta":
                    tools[event["index"]]["arguments"] += delta["partial_json"]
            elif kind == "message_delta":
                usage["output_tokens"] = event.get("usage", {}).get(
                    "output_tokens", usage["output_tokens"]
                )
            elif kind == "message_stop":
                for index, tool in tools.items():
                    tool["arguments"] = tool["arguments"] or tool["initial"]
                    blocks[index]["input"] = (
                        json.loads(tool["arguments"])
                        if isinstance(tool["arguments"], str)
                        else tool["arguments"]
                    )
                    yield tool_event(tool)
                yield state_event(entry, content=[blocks[i] for i in sorted(blocks)])
                yield {"type": "usage", **usage}
                return
        raise ProviderError()
