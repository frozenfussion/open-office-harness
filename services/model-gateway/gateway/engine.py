# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import aclosing
from decimal import Decimal
from typing import Any

import httpx
import psycopg

from gateway.adapters import resolve
from gateway.adapters.common import failure_info
from gateway.database import Database
from gateway.models import Call, Entry, GatewayError
from gateway.registry import Registry

logger = logging.getLogger("gateway")


def cost(entry: Entry, input_tokens: int, output_tokens: int) -> Decimal:
    return (
        (
            input_tokens * entry.input_price_per_million
            + output_tokens * entry.output_price_per_million
        )
        / Decimal(1_000_000)
    ).quantize(Decimal("0.000001"))


class Engine:
    def __init__(
        self, client: httpx.AsyncClient, registry: Registry, db: Database
    ) -> None:
        self.client, self.registry, self.db = client, registry, db

    async def events(
        self, call: Call, *, provider_details: bool = False
    ) -> AsyncIterator[dict[str, Any]]:
        entries = await self.registry.get(call.purpose, call.tier)
        entries = [
            e
            for e in entries
            if e.purpose == call.purpose
            and e.tier == call.tier
            and e.deleted_at is None
            and (call.model_entry_id is None or e.id == call.model_entry_id)
        ]
        supported = []
        for entry in entries:
            if resolve(entry) is None:
                logger.warning(
                    json.dumps(
                        {
                            "message": "unsupported connection type",
                            "model_entry_id": str(entry.id),
                        }
                    )
                )
            else:
                supported.append(entry)
        if not supported:
            raise GatewayError(
                404, "no_model", "No model is configured for this purpose and tier"
            )
        supported.sort(key=lambda e: (e.role != "main", e.priority, e.created_at))
        reasons = []
        for entry in supported:
            start = time.monotonic()
            count, spent = await self.db.limits(entry, call)
            reason = (
                "skipped_budget"
                if entry.daily_budget > 0 and spent >= entry.daily_budget
                else "skipped_rate"
                if count >= entry.rate_limit_per_minute
                else None
            )
            if reason:
                await self.db.record(entry, call, reason, 0, 0, Decimal(0), 0)
                reasons.append(reason)
                continue
            input_tokens = output_tokens = 0
            started = False
            recorded = False
            provider_attempted = False
            provider_finished = False
            try:
                key = await self.registry.key(entry)
                provider_attempted = True
                async with aclosing(
                    resolve(entry)(self.client, entry, key, call)
                ) as output:
                    async for event in output:
                        if event["type"] == "usage":
                            input_tokens, output_tokens = (
                                event["input_tokens"],
                                event["output_tokens"],
                            )
                        elif event["type"] in {"delta", "thinking", "tool_call"}:
                            started = True
                            yield event
                provider_finished = True
                total = cost(entry, input_tokens, output_tokens)
                await self.db.record(
                    entry,
                    call,
                    "ok",
                    input_tokens,
                    output_tokens,
                    total,
                    int((time.monotonic() - start) * 1000),
                )
                recorded = True
                yield {
                    "type": "completed",
                    "model_entry_id": str(entry.id),
                    "model_title": entry.title,
                    "thinking_applied": call.thinking
                    or entry.request_settings_thinking_off is not None,
                    "tier": entry.tier,
                    "usage": {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                    },
                    "cost_usd": float(total),
                }
                return
            except asyncio.CancelledError, GeneratorExit:
                if recorded:
                    raise
                await asyncio.shield(
                    self.db.record(
                        entry,
                        call,
                        "failed",
                        input_tokens,
                        output_tokens,
                        cost(entry, input_tokens, output_tokens),
                        int((time.monotonic() - start) * 1000),
                    )
                )
                raise
            except (
                httpx.HTTPError,
                ValueError,
                KeyError,
                TypeError,
                RuntimeError,
                psycopg.Error,
            ) as error:
                status, message, reason = (
                    failure_info(error)
                    if provider_attempted and not provider_finished
                    else (None, None, "bad_answer")
                )
                if provider_attempted and not provider_finished:
                    logger.warning(
                        json.dumps(
                            {
                                "message": "provider_failed",
                                "model_entry_id": str(entry.id),
                                "provider_status": status,
                                "reason": reason,
                            }
                        )
                    )
                await self.db.record(
                    entry,
                    call,
                    "failed",
                    input_tokens,
                    output_tokens,
                    cost(entry, input_tokens, output_tokens),
                    int((time.monotonic() - start) * 1000),
                )
                if provider_details and call.model_entry_id is not None:
                    raise GatewayError(
                        503,
                        "unavailable",
                        "The model did not answer. Try again.",
                        provider_status=status,
                        provider_message=message,
                    ) from None
                if started:
                    yield {
                        "type": "failed",
                        "error": {
                            "code": "unavailable",
                            "message": "The model did not answer. Try again.",
                        },
                    }
                    return
                reasons.append("failed")
                logger.info(
                    json.dumps({"message": "failover", "model_entry_id": str(entry.id)})
                )
        if all(reason == "skipped_budget" for reason in reasons):
            raise GatewayError(
                503, "budget_exceeded", "Every model is over its daily budget"
            )
        if "failed" not in reasons and "skipped_rate" in reasons:
            raise GatewayError(
                429,
                "rate_limited",
                "No model was called; at least one model is rate limited",
            )
        raise GatewayError(503, "unavailable", "The model did not answer. Try again.")
