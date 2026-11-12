# SPDX-License-Identifier: AGPL-3.0-only
import math
from typing import Any

import httpx

from consumer.config import Config
from consumer.events import outgoing
from consumer.identity import Identity


class Safety:
    def __init__(
        self, config: Config, client: httpx.AsyncClient, identity: Identity, bus: Any
    ) -> None:
        self.config, self.client, self.identity, self.bus = (
            config,
            client,
            identity,
            bus,
        )

    async def handle(self, topic: str, event: dict[str, Any]) -> None:
        payload = event["payload"]
        if topic == "skill.results" and payload["status"] != "completed":
            return
        text = (
            payload["text"]
            if topic == "chat.messages"
            else payload["output"]["summary"]
        )
        try:
            token = await self.identity.service_token()
            response = await self.client.post(
                self.config.gateway_url + "/v1/classify",
                headers={
                    "Authorization": "Bearer " + token,
                    "X-Correlation-Id": event["correlation_id"],
                },
                json={
                    "text": text[:20000],
                    "questions": self.config.questions,
                    "user_id": event["user_id"],
                },
            )
            scores = None
            if response.status_code == 404:
                if response.json().get("code") != "no_model":
                    raise ValueError("unexpected_missing_classifier")
                outcome = "skipped_no_classifier"
            elif response.status_code == 429:
                outcome = "skipped_rate_limited"
            elif response.status_code == 503:
                if response.json().get("code") not in {
                    "unavailable",
                    "budget_exceeded",
                    "registry_unavailable",
                }:
                    raise ValueError("unexpected_unavailable")
                outcome = "skipped_unavailable"
            else:
                response.raise_for_status()
                scores = {
                    key: response.json()["scores"][key] for key in self.config.questions
                }
                if any(
                    isinstance(v, bool)
                    or not isinstance(v, (int, float))
                    or not math.isfinite(v)
                    or not 0 <= v <= 1
                    for v in scores.values()
                ):
                    raise ValueError("invalid_scores")
                outcome = (
                    "flagged"
                    if any(v >= self.config.threshold for v in scores.values())
                    else "clear"
                )
        except httpx.HTTPError:
            raise RuntimeError("classifier_failed") from None
        audit = {
            "actor": "safety-watcher",
            "action": "safety.classify",
            "target": topic,
            "outcome": outcome,
        }
        if scores is not None:
            audit["scores"] = scores
        await self.bus.publish(
            "audit.events", outgoing(event, "safety-watcher", "audit.event", audit)
        )
        if outcome == "flagged":
            details = {
                key: payload[key]
                for key in ("conversation_id", "message_id", "skill")
                if key in payload
            }
            details.update(source=topic, scores=scores, excerpt=text[:300])
            await self.bus.publish(
                "approvals.requested",
                outgoing(
                    event,
                    "safety-watcher",
                    "approval.requested",
                    {
                        "action": "safety.flag",
                        "details": details,
                        "risk": "safety",
                        "requested_by": "safety-watcher",
                    },
                ),
            )
