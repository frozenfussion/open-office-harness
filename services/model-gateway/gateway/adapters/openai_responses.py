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
            result.append(
                {
                    "type": "function_call_output",
                    "call_id": message.tool_call_id,
                    "output": message.content,
                }
            )
        elif message.role == "assistant":
            state = matching_state(message, entry)
            if "output" in state:
                result.extend(state["output"])
            else:
                if message.content:
                    result.append({"role": "assistant", "content": message.content})
                result.extend(
                    {
                        "type": "function_call",
                        "call_id": t.id,
                        "name": t.name,
                        "arguments": json.dumps(t.arguments),
                    }
                    for t in message.tool_calls
                )
        else:
            result.append({"role": message.role, "content": message.content})
    return result


async def run(
    client: httpx.AsyncClient, entry: Entry, key: str, call: Call
) -> AsyncIterator[dict[str, Any]]:
    body = {
        "model": entry.model_id,
        "input": messages(call, entry),
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
    body = request_body(body, entry, call)
    body["store"] = False
    body["include"] = list(
        dict.fromkeys([*(body.get("include") or []), "reasoning.encrypted_content"])
    )
    yield {
        "type": "tool_choice_applied",
        "applied": forced_choice(body, call, entry.api_type),
    }
    reasoning = body.get("reasoning")
    summary_requested = (
        isinstance(reasoning, dict)
        and isinstance(reasoning.get("summary"), str)
        and bool(reasoning["summary"])
    )
    async with client.stream(
        "POST",
        entry.endpoint_url.rstrip("/") + "/responses",
        headers={"Authorization": "Bearer " + key},
        json=body,
        timeout=entry.timeout_seconds,
    ) as response:
        await check_response(response, key)
        if not call.stream:
            result = json.loads(await response.aread())
            if result.get("status") in {"failed", "incomplete"}:
                raise ProviderError()
            thinking_seen = False
            for item in result["output"]:
                if item["type"] == "message":
                    for content in item.get("content", []):
                        if content["type"] == "output_text" and content["text"]:
                            yield {"type": "delta", "text": content["text"]}
                elif item["type"] == "reasoning" and summary_requested:
                    for summary in item.get("summary", []):
                        if isinstance(summary.get("text"), str) and summary["text"]:
                            if thinking_seen:
                                yield {"type": "thinking", "text": "\n\n"}
                            yield {"type": "thinking", "text": summary["text"]}
                            thinking_seen = True
                elif item["type"] == "function_call":
                    yield tool_event(
                        {
                            "id": item["call_id"],
                            "name": item["name"],
                            "arguments": item["arguments"],
                        }
                    )
            yield state_event(entry, output=result["output"])
            yield {
                "type": "usage",
                **{
                    k: result.get("usage", {}).get(k, 0)
                    for k in ("input_tokens", "output_tokens")
                },
            }
            return
        tools: dict[str, dict[str, str]] = {}
        output: dict[int, dict[str, Any]] = {}
        thinking_seen = False
        new_part = False
        async for event in sse(response):
            kind = event.get("type")
            if kind in {"response.failed", "response.incomplete", "error"}:
                raise ProviderError()
            if kind == "response.output_text.delta" and event["delta"]:
                yield {"type": "delta", "text": event["delta"]}
            elif kind == "response.reasoning_summary_part.added" and summary_requested:
                new_part = thinking_seen
            elif kind == "response.reasoning_summary_text.delta" and summary_requested:
                if isinstance(event.get("delta"), str) and event["delta"]:
                    if new_part:
                        yield {"type": "thinking", "text": "\n\n"}
                    yield {"type": "thinking", "text": event["delta"]}
                    thinking_seen = True
                    new_part = False
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
            elif kind == "response.output_item.done":
                output[event["output_index"]] = event["item"]
            elif kind == "response.completed":
                yield state_event(
                    entry,
                    output=event["response"].get(
                        "output", [output[i] for i in sorted(output)]
                    ),
                )
                for tool in tools.values():
                    yield tool_event(tool)
                usage = event["response"].get("usage") or {}
                yield {
                    "type": "usage",
                    **{k: usage.get(k, 0) for k in ("input_tokens", "output_tokens")},
                }
                return
        raise ProviderError()
