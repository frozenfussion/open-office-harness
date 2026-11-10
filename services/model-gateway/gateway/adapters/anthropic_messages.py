# SPDX-License-Identifier: AGPL-3.0-only
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from gateway.models import Call, Entry

from .common import ProviderError, check_response, request_body, sse, tool_event


async def run(
    client: httpx.AsyncClient, entry: Entry, key: str, call: Call
) -> AsyncIterator[dict[str, Any]]:
    body = {
        "model": entry.model_id,
        "messages": [m.model_dump() for m in call.messages if m.role != "system"],
        "max_tokens": 4096,
        "stream": call.stream,
    }
    system = "\n".join(m.content for m in call.messages if m.role == "system")
    if system:
        body["system"] = system
    if call.tools:
        body["tools"] = [t.model_dump() for t in call.tools]
    async with client.stream(
        "POST",
        entry.endpoint_url.rstrip("/") + "/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        json=request_body(body, entry, call),
        timeout=entry.timeout_seconds,
    ) as response:
        await check_response(response, key)
        if not call.stream:
            result = json.loads(await response.aread())
            for block in result["content"]:
                if block["type"] == "thinking" and block.get("thinking"):
                    yield {"type": "thinking", "text": block["thinking"]}
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
            yield {
                "type": "usage",
                **{
                    k: result.get("usage", {}).get(k, 0)
                    for k in ("input_tokens", "output_tokens")
                },
            }
            return
        tools: dict[int, dict[str, Any]] = {}
        redacted_indexes: set[int] = set()
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
                block = event["content_block"]
                if block["type"] == "redacted_thinking":
                    redacted_indexes.add(event["index"])
                elif block["type"] == "thinking" and block.get("thinking"):
                    yield {"type": "thinking", "text": block["thinking"]}
                elif block["type"] == "tool_use":
                    tools[event["index"]] = {
                        "id": block["id"],
                        "name": block["name"],
                        "arguments": "",
                        "initial": block.get("input", {}),
                    }
            elif kind == "content_block_delta":
                delta = event["delta"]
                if (
                    delta["type"] == "thinking_delta"
                    and event.get("index") not in redacted_indexes
                    and delta.get("thinking")
                ):
                    yield {"type": "thinking", "text": delta["thinking"]}
                elif delta["type"] == "text_delta" and delta["text"]:
                    yield {"type": "delta", "text": delta["text"]}
                elif delta["type"] == "input_json_delta":
                    tools[event["index"]]["arguments"] += delta["partial_json"]
            elif kind == "message_delta":
                usage["output_tokens"] = event.get("usage", {}).get(
                    "output_tokens", usage["output_tokens"]
                )
            elif kind == "message_stop":
                for tool in tools.values():
                    tool["arguments"] = tool["arguments"] or tool["initial"]
                    yield tool_event(tool)
                yield {"type": "usage", **usage}
                return
        raise ProviderError()
