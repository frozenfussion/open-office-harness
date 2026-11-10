# SPDX-License-Identifier: AGPL-3.0-only
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from gateway.models import Call, Entry

from .common import ProviderError, check_response, request_body, sse, tool_event


def reasoning_text(message: dict[str, Any]) -> str | None:
    for field in ("reasoning_content", "reasoning"):
        text = message.get(field)
        if isinstance(text, str) and text:
            return text
    return None


async def run(
    client: httpx.AsyncClient, entry: Entry, key: str, call: Call
) -> AsyncIterator[dict[str, Any]]:
    body = {
        "model": entry.model_id,
        "messages": [m.model_dump() for m in call.messages],
        "stream": call.stream,
    }
    if call.tools:
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in call.tools
        ]
    if call.stream:
        body["stream_options"] = {"include_usage": True}
    body = request_body(body, entry, call)
    async with client.stream(
        "POST",
        entry.endpoint_url.rstrip("/") + "/chat/completions",
        headers={"Authorization": "Bearer " + key},
        json=body,
        timeout=entry.timeout_seconds,
    ) as response:
        await check_response(response, key)
        if not call.stream:
            result = json.loads(await response.aread())
            message = result["choices"][0]["message"]
            if text := reasoning_text(message):
                yield {"type": "thinking", "text": text}
            if message.get("content"):
                yield {"type": "delta", "text": message["content"]}
            for tool in message.get("tool_calls", []):
                yield tool_event({"id": tool["id"], **tool["function"]})
            usage = result.get("usage") or {}
            yield {
                "type": "usage",
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            }
            return
        tools: dict[int, dict[str, str]] = {}
        usage = {}
        finished = False
        async for chunk in sse(response):
            if chunk.get("error"):
                raise ProviderError()
            if chunk.get("usage") is not None:
                usage = chunk["usage"]
            if chunk.get("type") == "done":
                finished = True
                break
            for choice in chunk.get("choices", []):
                if choice.get("finish_reason") is not None:
                    finished = True
                delta = choice.get("delta", {})
                if text := reasoning_text(delta):
                    yield {"type": "thinking", "text": text}
                if delta.get("content"):
                    yield {"type": "delta", "text": delta["content"]}
                for part in delta.get("tool_calls", []):
                    tool = tools.setdefault(
                        part["index"], {"id": "", "name": "", "arguments": ""}
                    )
                    tool["id"] += part.get("id") or ""
                    tool["name"] += (part.get("function") or {}).get("name") or ""
                    tool["arguments"] += (part.get("function") or {}).get(
                        "arguments"
                    ) or ""
        if not finished:
            raise ProviderError()
        for tool in tools.values():
            yield tool_event(tool)
        yield {
            "type": "usage",
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        }
