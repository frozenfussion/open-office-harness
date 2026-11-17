# SPDX-License-Identifier: AGPL-3.0-only
import base64
import importlib
import json
import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
import pytest
import respx
from conftest import FakeDatabase, FakeRegistry
from test_adapters import TYPES, answer, chunks
from test_http_identity_registry import token

from gateway.adapters import resolve
from gateway.engine import Engine
from gateway.models import Call, Entry, GatewayError

DATA = base64.b64encode(b"synthetic-picture-private-bytes").decode()
IMAGE = {"media_type": "image/png", "data": DATA}
MESSAGE = {"role": "user", "content": "Example", "images": [IMAGE]}


def picture_call(call: Call, **changes: Any) -> Call:
    return Call.model_validate(call.model_dump() | {"messages": [MESSAGE]} | changes)


INVALID_MESSAGES = [[MESSAGE | {"role": role}] for role in ("system", "assistant")] + [
    [MESSAGE | {"role": "tool", "tool_call_id": "fake-call"}],
    [MESSAGE | {"images": [IMAGE, IMAGE]}],
    [MESSAGE | {"images": [IMAGE | {"extra": "no"}]}],
    [MESSAGE | {"images": [IMAGE | {"media_type": "image/gif"}]}],
    *[
        [MESSAGE | {"images": [IMAGE | {"data": data}]}]
        for data in ("", "A" * 9786716, "not base64!", "é", "YQ=", "YQ==\n")
    ],
    [MESSAGE] * 4,
    [MESSAGE | {"content": ""}],
    [MESSAGE | {"content": None}],
]


@pytest.mark.parametrize(
    "messages",
    INVALID_MESSAGES,
    ids=[f"invalid-{i}" for i in range(len(INVALID_MESSAGES))],
)
def test_invalid_pictures_are_400_without_provider_or_data_logs(
    http: tuple, call: Call, messages: list[dict], caplog: pytest.LogCaptureFixture
) -> None:
    client, key = http
    caplog.set_level(logging.INFO)
    with respx.mock as mock:
        response = client.post(
            "/v1/call",
            headers={"Authorization": "Bearer " + token(key)},
            json=call.model_dump() | {"messages": messages},
        )
        assert not mock.calls
    assert response.status_code == 400
    assert response.json() == {"code": "invalid_input", "message": "Invalid request"}
    assert DATA not in repr([record.__dict__ for record in caplog.records])


@pytest.mark.parametrize("mime", ["image/png", "image/jpeg"])
def test_picture_boundaries(call: Call, mime: str) -> None:
    data = base64.b64encode(b"a" * 7340032).decode()
    assert len(data) == 9786712
    message = MESSAGE | {"images": [{"media_type": mime, "data": data}]}
    assert len(picture_call(call, messages=[message] * 3).messages) == 3


@pytest.mark.anyio
@pytest.mark.parametrize("kind", TYPES)
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("mime", ["image/png", "image/jpeg"])
async def test_adapter_picture_shape_and_unchanged_text_bytes(
    entry: Entry, call: Call, kind: str, stream: bool, mime: str
) -> None:
    entry = entry.model_copy(update={"api_type": kind})
    plain = call.model_copy(update={"stream": stream})
    picture = picture_call(
        plain,
        messages=[
            {"role": "system", "content": "Fake instruction"},
            MESSAGE | {"images": [IMAGE | {"media_type": mime}]},
        ],
    )
    image_url = f"data:{mime};base64,{DATA}"
    expected = {
        TYPES[0]: [
            {"type": "text", "text": "Example"},
            {"type": "image_url", "image_url": {"url": image_url}},
        ],
        TYPES[1]: [
            {"type": "input_text", "text": "Example"},
            {"type": "input_image", "image_url": image_url},
        ],
        TYPES[2]: [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": mime, "data": DATA},
            },
            {"type": "text", "text": "Example"},
        ],
    }[kind]
    with respx.mock as mock:
        route = mock.post(url__startswith=entry.endpoint_url).mock(
            return_value=(
                httpx.Response(
                    200,
                    text="".join(
                        "data: " + json.dumps(event) + "\n\n" for event in chunks(kind)
                    ),
                )
                if stream
                else httpx.Response(200, json=answer(kind))
            )
        )
        async with httpx.AsyncClient() as client:
            for body in (plain, picture):
                _ = [
                    event
                    async for event in resolve(entry)(client, entry, "fake-key", body)
                ]
        original = route.calls[0].request.content
        body = json.loads(route.calls[1].request.content)
        field = "input" if kind == TYPES[1] else "messages"
        assert body[field][-1] == {"role": "user", "content": expected}
        body[field][-1]["content"] = "Example"
        assert httpx.Request("POST", entry.endpoint_url, json=body).content == original
        # Fixed pre-picture user-turn bytes, independent of the modified implementation.
        assert (
            json.dumps(
                importlib.import_module("gateway.adapters." + kind).messages(
                    plain, entry
                )[-1],
                separators=(",", ":"),
            ).encode()
            == b'{"role":"user","content":"Example"}'
        )


class PictureLimits(FakeDatabase):
    def __init__(self, backup: Entry, outcome: str) -> None:
        super().__init__()
        self.backup, self.outcome = backup, outcome

    async def limits(self, entry: Entry, call: Call) -> tuple:
        if entry.id == self.backup.id:
            if self.outcome == "rate":
                return entry.rate_limit_per_minute, Decimal(0)
            if self.outcome == "budget":
                return 0, entry.daily_budget
        return 0, Decimal(0)


@pytest.mark.anyio
@pytest.mark.parametrize("kind", TYPES)
@pytest.mark.parametrize("status", [400, 413, 422])
@pytest.mark.parametrize("outcome", ["refused", "down", "rate", "budget", "success"])
async def test_refusal_failover_health_and_private_logs(
    entry: Entry,
    call: Call,
    kind: str,
    status: int,
    outcome: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    entry = entry.model_copy(update={"api_type": kind})
    backup = entry.model_copy(
        update={
            "id": UUID(int=2),
            "role": "backup",
            "endpoint_url": "https://backup.invalid",
            "daily_budget": Decimal(1),
        }
    )
    db = PictureLimits(backup, outcome)
    published = []

    class Publisher:
        async def publish(self, value: dict) -> None:
            published.append(value)

    with respx.mock as mock:
        main = mock.post(url__startswith=entry.endpoint_url).mock(
            return_value=httpx.Response(status, json={"error": {"message": DATA}})
        )
        fallback = mock.post(url__startswith=backup.endpoint_url).mock(
            return_value=(
                httpx.Response(200, json=answer(kind))
                if outcome == "success"
                else httpx.Response(status if outcome == "refused" else 503, text=DATA)
            )
        )
        async with httpx.AsyncClient() as client:
            engine = Engine(client, FakeRegistry([entry, backup]), db, Publisher())
            engine.health_states[entry.id] = "ok"
            engine.health_states[backup.id] = "ok"
            if outcome == "success":
                events = [
                    e async for e in engine.events(picture_call(call, stream=False))
                ]
                assert events[-1]["type"] == "completed"
                assert events[-1]["usage"] == {"input_tokens": 8, "output_tokens": 3}
                assert events[-1]["cost_usd"] == 0.000028
            else:
                with pytest.raises(GatewayError) as error:
                    _ = [
                        e async for e in engine.events(picture_call(call, stream=False))
                    ]
                assert error.value.code == "image_refused" and error.value.status == 503
            await engine.drain_background()
        assert main.call_count == 1
        assert fallback.call_count == (0 if outcome in {"rate", "budget"} else 1)
        assert engine.health_states[entry.id] == "ok"
        assert engine.health_states[backup.id] == (
            "down" if outcome == "down" else "ok"
        )
    assert DATA not in repr([record.__dict__ for record in caplog.records])
    assert DATA not in json.dumps(published)
    assert published[0]["payload"]["outcome"] == (
        "ok" if outcome == "success" else "failed"
    )


@pytest.mark.anyio
@pytest.mark.parametrize("kind", TYPES)
@pytest.mark.parametrize("status", [400, 413, 422])
async def test_same_errors_without_picture_keep_old_health_and_code(
    entry: Entry, call: Call, kind: str, status: int
) -> None:
    entry = entry.model_copy(update={"api_type": kind})
    with respx.mock as mock:
        mock.post(url__startswith=entry.endpoint_url).mock(
            return_value=httpx.Response(status)
        )
        async with httpx.AsyncClient() as client:
            engine = Engine(client, FakeRegistry([entry]), FakeDatabase())
            with pytest.raises(GatewayError) as error:
                _ = [e async for e in engine.events(call)]
            await engine.drain_background()
    assert error.value.code == "unavailable"
    assert engine.health_states[entry.id] == "down"


@pytest.mark.anyio
@pytest.mark.parametrize("kind", TYPES)
@pytest.mark.parametrize("second_status", [200, 400, 413, 422])
async def test_forced_tool_retries_before_picture_refusal(
    entry: Entry, call: Call, kind: str, second_status: int
) -> None:
    entry = entry.model_copy(update={"api_type": kind})
    call = picture_call(call, stream=False, tool_choice={"name": "fake_tool"})
    with respx.mock as mock:
        route = mock.post(url__startswith=entry.endpoint_url).mock(
            side_effect=[
                httpx.Response(400),
                httpx.Response(
                    second_status, json=answer(kind) if second_status == 200 else {}
                ),
            ]
        )
        async with httpx.AsyncClient() as client:
            engine = Engine(client, FakeRegistry([entry]), FakeDatabase())
            engine.health_states[entry.id] = "ok"
            if second_status == 200:
                events = [e async for e in engine.events(call)]
                assert events[-1]["type"] == "completed"
                assert events[-1]["tool_choice_applied"] is False
            else:
                with pytest.raises(GatewayError) as error:
                    _ = [e async for e in engine.events(call)]
                assert error.value.code == "image_refused"
            await engine.drain_background()
        assert route.call_count == 2
        bodies = [json.loads(c.request.content) for c in route.calls]
        assert isinstance(bodies[0]["tool_choice"], dict)
        assert bodies[1]["tool_choice"] == (
            {"type": "auto"} if kind == TYPES[2] else "auto"
        )
        field = "input" if kind == TYPES[1] else "messages"
        assert bodies[0][field] == bodies[1][field]
        assert DATA in json.dumps(bodies[1][field])
        assert engine.health_states[entry.id] == "ok"


@pytest.mark.parametrize("stream", [False, True])
def test_http_picture_refusal(http: tuple, call: Call, stream: bool) -> None:
    client, key = http
    with respx.mock as mock:
        mock.post(url__startswith="https://example.invalid").mock(
            return_value=httpx.Response(413)
        )
        response = client.post(
            "/v1/call",
            headers={"Authorization": "Bearer " + token(key)},
            json=picture_call(call, stream=stream).model_dump(),
        )
    assert response.status_code == 503
    assert response.json()["code"] == "image_refused"


def test_stream_keeps_prior_picture_refusal_after_backup_output(
    http: tuple, entry: Entry, call: Call
) -> None:
    client, key = http
    engine = client.app.state.engine
    backup = entry.model_copy(
        update={
            "id": UUID(int=2),
            "role": "backup",
            "endpoint_url": "https://backup.invalid",
        }
    )
    engine.registry = FakeRegistry([entry, backup])
    with respx.mock as mock:
        mock.post(url__startswith=entry.endpoint_url).mock(
            return_value=httpx.Response(400)
        )
        mock.post(url__startswith=backup.endpoint_url).mock(
            return_value=httpx.Response(
                200, text='data: {"choices":[{"delta":{"content":"Partial"}}]}\n\n'
            )
        )
        response = client.post(
            "/v1/call",
            headers={"Authorization": "Bearer " + token(key)},
            json=picture_call(call).model_dump(),
        )
    assert response.status_code == 200
    events = [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert events[0] == {"type": "delta", "text": "Partial"}
    assert events[-1]["type"] == "failed"
    assert events[-1]["error"]["code"] == "image_refused"


@pytest.mark.anyio
async def test_backup_refusal_wins_after_main_connection_failure(
    entry: Entry, call: Call
) -> None:
    backup = entry.model_copy(
        update={
            "id": UUID(int=2),
            "role": "backup",
            "endpoint_url": "https://backup.invalid",
        }
    )
    with respx.mock as mock:
        mock.post(url__startswith=entry.endpoint_url).mock(
            side_effect=httpx.ConnectError("fake connection failure")
        )
        mock.post(url__startswith=backup.endpoint_url).mock(
            return_value=httpx.Response(422)
        )
        async with httpx.AsyncClient() as client:
            engine = Engine(client, FakeRegistry([entry, backup]), FakeDatabase())
            with pytest.raises(GatewayError) as error:
                _ = [e async for e in engine.events(picture_call(call))]
            await engine.drain_background()
    assert error.value.code == "image_refused"
    assert engine.health_states[entry.id] == "down"
    assert backup.id not in engine.health_states


@pytest.mark.anyio
@pytest.mark.parametrize("status", [400, 413, 422])
async def test_picture_refusal_status_after_output_is_an_ordinary_failure(
    entry: Entry, call: Call, status: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import AsyncIterator

    from gateway.adapters.common import ProviderError

    async def adapter(*args: Any) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "delta", "text": "Partial"}
        raise ProviderError(status, DATA)

    monkeypatch.setattr("gateway.engine.resolve", lambda _: adapter)
    async with httpx.AsyncClient() as client:
        engine = Engine(client, FakeRegistry([entry]), FakeDatabase())
        events = [e async for e in engine.events(picture_call(call))]
        await engine.drain_background()
    assert events[-1]["type"] == "failed"
    assert events[-1]["error"]["code"] == "unavailable"
    assert entry.id not in engine.health_states
