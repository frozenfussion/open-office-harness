# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from confluent_kafka import KafkaException, Producer

logger = logging.getLogger("gateway")


def envelope(
    correlation_id: UUID, user_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    return {
        "event_id": str(uuid4()),
        "type": "audit.event",
        "version": 1,
        "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "correlation_id": str(correlation_id),
        "user_id": user_id,
        "producer": "model-gateway",
        "payload": payload,
    }


class Events:
    def __init__(self, bootstrap: str, username: str, password: str) -> None:
        self.producer = Producer(
            {
                "bootstrap.servers": bootstrap,
                "security.protocol": "SASL_PLAINTEXT",
                "sasl.mechanism": "SCRAM-SHA-512",
                "sasl.username": username,
                "sasl.password": password,
                "enable.idempotence": True,
                "message.timeout.ms": 5000,
                "log_level": 0,
            }
        )

    def _publish(self, value: dict[str, Any]) -> None:
        errors = []
        self.producer.produce(
            "audit.events",
            key=value["correlation_id"],
            value=json.dumps(value),
            on_delivery=lambda error, message: errors.append(error) if error else None,
        )
        if self.producer.flush(6) or errors:
            raise RuntimeError("audit_unavailable")

    async def publish(self, value: dict[str, Any]) -> None:
        try:
            await asyncio.to_thread(self._publish, value)
        except KafkaException, BufferError:
            raise RuntimeError("audit_unavailable") from None
