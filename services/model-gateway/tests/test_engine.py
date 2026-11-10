# SPDX-License-Identifier: AGPL-3.0-only
import json
import logging
from decimal import Decimal
from uuid import UUID

import httpx
import pytest
import respx
from conftest import FakeDatabase, FakeRegistry

from gateway.engine import Engine, cost
from gateway.models import Call, Entry, GatewayError


@pytest.mark.anyio
@pytest.mark.parametrize("after_output", [False, True])
async def test_failover_boundary(
    entry: Entry, call: Call, after_output: bool, caplog: pytest.LogCaptureFixture
) -> None:
    backup = entry.model_copy(
        update={
            "id": UUID(int=2),
            "role": "backup",
            "endpoint_url": "https://backup.invalid",
        }
    )
    db = FakeDatabase()
    payload = 'data: {"choices":[{"delta":{"content":"partial"}}]}\n\ndata: {"error":{"message":"fake-provider-key"}}\n\n'
    with respx.mock as mock:
        main = mock.post("https://example.invalid/chat/completions").mock(
            return_value=httpx.Response(200, text=payload)
            if after_output
            else httpx.Response(500, text="fake-provider-key")
        )
        other = mock.post("https://backup.invalid/chat/completions").mock(
            return_value=httpx.Response(
                200,
                text='data: {"choices":[{"delta":{"content":"backup"},"finish_reason":"stop"}]}\n\n',
            )
        )
        caplog.set_level(logging.INFO)
        async with httpx.AsyncClient() as client:
            events = [
                e
                async for e in Engine(client, FakeRegistry([backup, entry]), db).events(
                    call
                )
            ]
        assert main.call_count == 1 and other.call_count == (0 if after_output else 1)
        assert events[0]["text"] == ("partial" if after_output else "backup")
        assert events[-1]["type"] == ("failed" if after_output else "completed")
        assert db.rows[0][2] == "failed"
        assert "fake-provider-key" not in caplog.text
        failures = [
            json.loads(record.getMessage())
            for record in caplog.records
            if record.name == "gateway" and '"provider_failed"' in record.getMessage()
        ]
        assert failures == [
            {
                "message": "provider_failed",
                "model_entry_id": str(entry.id),
                "provider_status": None if after_output else 500,
                "reason": "bad_answer" if after_output else "http",
            }
        ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "reason,status,code",
    [("rate", 429, "rate_limited"), ("budget", 503, "budget_exceeded")],
)
async def test_limits_skip(
    entry: Entry, call: Call, reason: str, status: int, code: str
) -> None:
    db = FakeDatabase()
    if reason == "rate":
        db.count = 2
    else:
        entry = entry.model_copy(update={"daily_budget": Decimal(1)})
        db.spent = Decimal(1)
    async with httpx.AsyncClient() as client:
        with pytest.raises(GatewayError) as error:
            _ = [
                e async for e in Engine(client, FakeRegistry([entry]), db).events(call)
            ]
    assert (error.value.status, error.value.code) == (status, code)
    assert db.rows[0][2] == ("skipped_rate" if reason == "rate" else "skipped_budget")


@pytest.mark.anyio
async def test_zero_budget_and_cost(entry: Entry, call: Call) -> None:
    db = FakeDatabase()
    db.spent = Decimal(9999)
    call = call.model_copy(update={"stream": False})
    with respx.mock as mock:
        mock.post("https://example.invalid/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 250},
                },
            )
        )
        async with httpx.AsyncClient() as client:
            events = [
                e async for e in Engine(client, FakeRegistry([entry]), db).events(call)
            ]
    assert events[-1]["cost_usd"] == 0.003
    assert cost(entry, 1000, 250) == Decimal("0.003000")
    assert db.rows[0][2] == "ok"


@pytest.mark.anyio
@pytest.mark.parametrize("pinned", [False, True])
async def test_unsupported_and_pinned_mismatch(
    entry: Entry, call: Call, pinned: bool, caplog: pytest.LogCaptureFixture
) -> None:
    if pinned:
        call = call.model_copy(update={"model_entry_id": UUID(int=9)})
    else:
        entry = entry.model_copy(update={"api_type": "fake-unsupported"})
    async with httpx.AsyncClient() as client:
        with pytest.raises(GatewayError, match="no_model"):
            _ = [
                e
                async for e in Engine(
                    client, FakeRegistry([entry]), FakeDatabase()
                ).events(call)
            ]
    if not pinned:
        assert "unsupported connection type" in caplog.text


@pytest.mark.anyio
async def test_order_and_pinned_no_failover(entry: Entry, call: Call) -> None:
    older = entry.model_copy(update={"id": UUID(int=2), "priority": 1})
    with respx.mock as mock:
        route = mock.post("https://example.invalid/chat/completions").mock(
            return_value=httpx.Response(500)
        )
        async with httpx.AsyncClient() as client:
            db = FakeDatabase()
            with pytest.raises(GatewayError, match="unavailable"):
                _ = [
                    e
                    async for e in Engine(
                        client, FakeRegistry([entry, older]), db
                    ).events(call)
                ]
            assert [row[0].id for row in db.rows] == [older.id, entry.id]
            db.rows.clear()
            pinned = call.model_copy(update={"model_entry_id": entry.id})
            with pytest.raises(GatewayError):
                _ = [
                    e
                    async for e in Engine(
                        client, FakeRegistry([older, entry]), db
                    ).events(pinned)
                ]
            assert len(db.rows) == 1 and route.call_count == 3


@pytest.mark.anyio
async def test_closing_stream_records_failure(entry: Entry, call: Call) -> None:
    db = FakeDatabase()
    with respx.mock as mock:
        mock.post("https://example.invalid/chat/completions").mock(
            return_value=httpx.Response(
                200, text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            )
        )
        async with httpx.AsyncClient() as client:
            events = Engine(client, FakeRegistry([entry]), db).events(call)
            assert (await anext(events))["text"] == "partial"
            await events.aclose()
    assert len(db.rows) == 1 and db.rows[0][2] == "failed"


@pytest.mark.anyio
async def test_skip_main_then_backup(entry: Entry, call: Call) -> None:
    db = FakeDatabase()
    db.spent = Decimal(1)
    main = entry.model_copy(update={"daily_budget": Decimal(1)})
    backup = entry.model_copy(update={"id": UUID(int=2), "role": "backup"})
    with respx.mock as mock:
        route = mock.post("https://example.invalid/chat/completions").mock(
            return_value=httpx.Response(
                200,
                text='data: {"choices":[{"delta":{"content":"backup"},"finish_reason":"stop"}]}\n\n',
            )
        )
        async with httpx.AsyncClient() as client:
            events = [
                e
                async for e in Engine(client, FakeRegistry([backup, main]), db).events(
                    call
                )
            ]
        assert route.call_count == 1 and events[-1]["model_entry_id"] == str(backup.id)
    assert [row[2] for row in db.rows] == ["skipped_budget", "ok"]


@pytest.mark.anyio
async def test_mixed_skips_return_rate_limited(entry: Entry, call: Call) -> None:
    db = FakeDatabase()
    db.spent = Decimal(1)
    db.count = 2
    budget = entry.model_copy(update={"daily_budget": Decimal(1)})
    rate = entry.model_copy(update={"id": UUID(int=2), "role": "backup"})
    with respx.mock as mock:
        async with httpx.AsyncClient() as client:
            with pytest.raises(GatewayError) as error:
                _ = [
                    event
                    async for event in Engine(
                        client, FakeRegistry([budget, rate]), db
                    ).events(call)
                ]
        assert not mock.calls
    assert (error.value.status, error.value.code) == (429, "rate_limited")
    assert [row[2] for row in db.rows] == ["skipped_budget", "skipped_rate"]
