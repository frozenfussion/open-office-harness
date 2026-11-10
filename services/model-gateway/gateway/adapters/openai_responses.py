# SPDX-License-Identifier: AGPL-3.0-only
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from gateway.models import Call, Entry

from .common import ProviderError, settings, sse, tool_event


async def run(
    client: httpx.AsyncClient, entry: Entry, key: str, call: Call
) -> AsyncIterator[dict[str, Any]]:
    body = {
        "model": entry.model_id,
        "input": [m.model_dump() for m in call.messages if m.role != "system"],
        "stream": call.stream,
        "store": False,
    }
    instructions = "\n".join(m.content for m in call.messages if m.role == "system")
    if instructions:
        body["instructions"] = instructions
    if call.tools:
        body["tools"] = [
            {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
                "strict": False,
            }
            for t in call.tools
        ]
    async with client.stream(
        "POST",
        entry.endpoint_url.rstrip("/") + "/responses",
        headers={"Authorization": "Bearer " + key},
        json=settings(body, entry.request_settings),
        timeout=entry.timeout_seconds,
    ) as response:
        response.raise_for_status()
        if not call.stream:
            result = json.loads(await response.aread())
            if result.get("status") in {"failed", "incomplete"}:
                raise ProviderError()
            for item in result["output"]:
                if item["type"] == "message":
                    for content in item.get("content", []):
                        if content["type"] == "output_text" and content["text"]:
                            yield {"type": "delta", "text": content["text"]}
                elif item["type"] == "function_call":
                    yield tool_event(
                        {
                            "id": item["call_id"],
                            "name": item["name"],
                            "arguments": item["arguments"],
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
        tools: dict[str, dict[str, str]] = {}
        async for event in sse(response):
            kind = event.get("type")
            if kind in {"response.failed", "response.incomplete", "error"}:
                raise ProviderError()
            if kind == "response.output_text.delta" and event["delta"]:
                yield {"type": "delta", "text": event["delta"]}
            elif (
                kind == "response.output_item.added"
                and event["item"]["type"] == "function_call"
            ):
                item = event["item"]
                tools[item["id"]] = {
                    "id": item["call_id"],
                    "name": item["name"],
                    "arguments": item.get("arguments", ""),
                }
            elif kind == "response.function_call_arguments.delta":
                tools[event["item_id"]]["arguments"] += event["delta"]
            elif kind == "response.function_call_arguments.done":
                tools[event["item_id"]]["arguments"] = event["arguments"]
            elif kind == "response.completed":
                for tool in tools.values():
                    yield tool_event(tool)
                usage = event["response"].get("usage") or {}
                yield {
                    "type": "usage",
                    **{k: usage.get(k, 0) for k in ("input_tokens", "output_tokens")},
                }
                return
        raise ProviderError()
