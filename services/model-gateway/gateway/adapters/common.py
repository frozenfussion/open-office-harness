# SPDX-License-Identifier: AGPL-3.0-only
import json
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from gateway.models import Call, Entry


class ProviderError(RuntimeError):
    def __init__(self, status: int | None = None, message: str | None = None) -> None:
        self.status, self.provider_message = status, message
        super().__init__("provider_failed")


def sanitize_message(text: str, key: str) -> str:
    spans = [match.span() for match in re.finditer(r"sk-(?:ant-)?[A-Za-z0-9_-]+", text)]
    if key:
        if len(key) < 8:
            spans.extend(match.span() for match in re.finditer(re.escape(key), text))
        else:
            fragments = {key[i : i + 8] for i in range(len(key) - 7)}
            spans.extend(
                (i, i + 8) for i in range(len(text) - 7) if text[i : i + 8] in fragments
            )
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = merged[-1][0], max(merged[-1][1], end)
        else:
            merged.append((start, end))
    pieces = []
    previous = 0
    for start, end in merged:
        pieces.extend((text[previous:start], "[removed]"))
        previous = end
    pieces.append(text[previous:])
    return "".join(pieces)[:300]


async def check_response(response: httpx.Response, key: str) -> None:
    if 200 <= response.status_code < 300:
        return
    raw = bytearray()
    async for chunk in response.aiter_bytes(chunk_size=4096):
        raw.extend(chunk[: 4096 - len(raw)])
        if len(raw) >= 4096:
            break
    text = raw.decode("utf-8", errors="replace")
    try:
        value = json.loads(text)
        if (
            isinstance(value, dict)
            and isinstance(value.get("error"), dict)
            and isinstance(value["error"].get("message"), str)
        ):
            text = value["error"]["message"]
    except ValueError:
        pass
    raise ProviderError(
        response.status_code, sanitize_message(text, key) if text else None
    )


def failure_info(error: BaseException) -> tuple[int | None, str | None, str]:
    if isinstance(error, ProviderError):
        return (
            error.status,
            error.provider_message,
            "http" if error.status is not None else "bad_answer",
        )
    if isinstance(error, httpx.TimeoutException):
        return None, "time limit reached", "timeout"
    if isinstance(error, httpx.RequestError):
        return None, "could not connect", "connect"
    return None, None, "bad_answer"


def settings(body: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    result = body | extra
    return {key: value for key, value in result.items() if value is not None}


def request_body(body: dict[str, Any], entry: Entry, call: Call) -> dict[str, Any]:
    body = settings(body, entry.request_settings)
    if not call.thinking and entry.request_settings_thinking_off is not None:
        body = settings(body, entry.request_settings_thinking_off)
    return body


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
