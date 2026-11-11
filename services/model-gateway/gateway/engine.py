# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
import json
import logging
import math
import time
from collections.abc import AsyncIterator
from contextlib import aclosing
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx
import psycopg

from gateway.adapters import resolve
from gateway.adapters.common import failure_info
from gateway.database import Database
from gateway.events import envelope
from gateway.models import Call, Classify, Entry, GatewayError
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
        self,
        client: httpx.AsyncClient,
        registry: Registry,
        db: Database,
        publisher: Any = None,
    ) -> None:
        self.client, self.registry, self.db = client, registry, db
        self.publisher = publisher
        self.health_states: dict[UUID, str] = {}

    async def health(
        self, entry: Entry, status: str, reason: str | None = None
    ) -> None:
        if self.health_states.get(entry.id) == status:
            return
        self.health_states[entry.id] = status
        await self.registry.report_health(entry, status, reason)

    async def events(
        self,
        call: Call,
        *,
        provider_details: bool = False,
        correlation_id: UUID | None = None,
        classification: Classify | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        result: dict[str, Any] = {}
        succeeded = False
        try:
            async with aclosing(
                self._events(
                    call,
                    provider_details=provider_details,
                    classification=classification,
                )
            ) as output:
                async for event in output:
                    if event["type"] == "audit_usage":
                        result = event
                        continue
                    if event["type"] == "completed":
                        result = event
                        succeeded = True
                    yield event
        finally:
            if self.publisher is not None:
                payload = {
                    "actor": call.user_id,
                    "action": "model.classify" if classification else "model.call",
                    "target": call.purpose
                    + (f":{call.tier}" if call.tier is not None else ""),
                    "outcome": "ok" if succeeded else "failed",
                    "tokens": sum(result.get("usage", {}).values()),
                    "cost_usd": result.get("cost_usd", 0),
                }
                for key in ("model_entry_id", "scores"):
                    if key in result:
                        payload[key] = result[key]
                if "model_title" in result:
                    payload["model"] = result["model_title"]
                try:
                    await self.publisher.publish(
                        envelope(correlation_id or uuid4(), call.user_id, payload)
                    )
                except RuntimeError, OSError, ValueError:
                    logger.warning(json.dumps({"message": "audit_publish_failed"}))

    async def classify(
        self,
        body: Classify,
        correlation_id: UUID | None = None,
        *,
        provider_details: bool = False,
    ) -> dict[str, Any]:
        call = Call(
            purpose="classification",
            user_id=body.user_id,
            model_entry_id=body.model_entry_id,
            stream=False,
            messages=[
                {
                    "role": "system",
                    "content": "Return exactly one JSON object mapping each question key to a probability from 0 to 1. No other text. Questions: "
                    + json.dumps(body.questions),
                },
                {"role": "user", "content": body.text},
            ],
        )
        result = None
        async for event in self.events(
            call,
            correlation_id=correlation_id,
            classification=body,
            provider_details=provider_details,
        ):
            if event["type"] == "completed":
                result = {
                    key: event[key]
                    for key in (
                        "scores",
                        "model_entry_id",
                        "model_title",
                        "usage",
                        "cost_usd",
                    )
                }
        if result is None:
            raise GatewayError(503, "unavailable", "The classifier did not answer")
        return result

    async def _events(
        self,
        call: Call,
        *,
        provider_details: bool = False,
        classification: Classify | None = None,
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
            if resolve(entry) is None and not (
                classification and entry.api_type == "jev_systemone"
            ):
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
            reasoning_state: dict[str, Any] = {"model_entry_id": str(entry.id)}
            tool_choice_applied = True
            text = ""
            scores = None
            started = False
            recorded = False
            provider_attempted = False
            provider_finished = False
            yield {
                "type": "audit_usage",
                "model_entry_id": str(entry.id),
                "model_title": entry.title,
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "cost_usd": 0,
            }
            try:
                key = await self.registry.key(entry)
                provider_attempted = True
                if classification and entry.api_type == "jev_systemone":
                    response = await self.client.post(
                        entry.endpoint_url.rstrip("/") + "/v1/systemone",
                        headers={"Authorization": "Bearer " + key} if key else {},
                        json={
                            "model": entry.model_id,
                            "state": classification.text,
                            "questions": {
                                k: {"type": "noul", "instructions": v}
                                for k, v in classification.questions.items()
                            },
                        },
                        timeout=entry.timeout_seconds,
                    )
                    from gateway.adapters.common import check_response

                    await check_response(response, key)
                    answer = response.json()
                    scores = {
                        k: answer["answers"][k]["noul"]
                        for k in classification.questions
                    }
                    usage = answer.get("usage") or {}
                    input_tokens, output_tokens = (
                        usage.get("input_tokens", 0),
                        usage.get("output_tokens", 0),
                    )
                else:
                    async with aclosing(
                        resolve(entry)(self.client, entry, key, call)
                    ) as output:
                        async for event in output:
                            if event["type"] == "usage":
                                input_tokens, output_tokens = (
                                    event["input_tokens"],
                                    event["output_tokens"],
                                )
                            elif event["type"] == "reasoning_state":
                                reasoning_state = event["state"]
                            elif event["type"] == "tool_choice_applied":
                                tool_choice_applied = event["applied"]
                            elif classification:
                                if event["type"] == "delta":
                                    text += event["text"]
                            elif event["type"] in {"delta", "thinking", "tool_call"}:
                                started = True
                                yield event
                    if classification:
                        answer = json.loads(text)
                        scores = {k: answer[k] for k in classification.questions}
                if classification and any(
                    isinstance(v, bool)
                    or not isinstance(v, (float, int))
                    or not math.isfinite(v)
                    or not 0 <= v <= 1
                    for v in scores.values()
                ):
                    raise ValueError("invalid_scores")
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
                await self.health(entry, "ok")
                yield {
                    "type": "completed",
                    "reasoning_state": reasoning_state,
                    "tool_choice_applied": tool_choice_applied,
                    **({"scores": scores} if classification else {}),
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
                if provider_attempted and not provider_finished and not started:
                    health_reason = (
                        f"http_{status}"
                        if status is not None
                        else "timeout"
                        if reason == "timeout"
                        else "connection"
                    )
                    await self.health(entry, "down", health_reason)
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
                yield {
                    "type": "audit_usage",
                    "model_entry_id": str(entry.id),
                    "model_title": entry.title,
                    "usage": {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                    },
                    "cost_usd": float(cost(entry, input_tokens, output_tokens)),
                }
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
