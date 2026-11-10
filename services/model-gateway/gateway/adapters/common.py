# SPDX-License-Identifier: AGPL-3.0-only
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx


class ProviderError(RuntimeError):
    pass


def settings(body: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    result = body | extra
    return {key: value for key, value in result.items() if value is not None}


def tool_event(tool: dict[str, Any]) -> dict[str, Any]:
    arguments = tool.get("arguments", "")
    if isinstance(arguments, str):
        arguments = json.loads(arguments or "{}")
    if not isinstance(arguments, dict):
        raise ProviderError()
    return {
        "type": "tool_call",
        "id": tool["id"],
        "name": tool["name"],
        "arguments": arguments,
    }


async def sse(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    data: list[str] = []
    async for line in response.aiter_lines():
        if line == "":
            if data:
                raw = "\n".join(data)
                data = []
                if raw == "[DONE]":
                    yield {"type": "done"}
                else:
                    yield json.loads(raw)
        elif line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
    if data:
        raw = "\n".join(data)
        yield {"type": "done"} if raw == "[DONE]" else json.loads(raw)
