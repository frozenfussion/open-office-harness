# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

from confluent_kafka import Consumer, KafkaException, Producer
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from opentelemetry.trace import SpanKind, Status, StatusCode

from consumer import tracing
from consumer.config import Config

logger = logging.getLogger("consumer")
NAMESPACE = UUID("6f1d5b7e-3c1a-4b8e-9a52-1f0c8f3e2d10")


def validator() -> Draft202012Validator:
    folder = Path(__file__).parent / "schemas"
    schema = json.loads((folder / "envelope.schema.json").read_text())
    for branch in schema["allOf"]:
        payload = branch["then"]["properties"]["payload"]
        branch["then"]["properties"]["payload"] = json.loads(
            (folder / payload["$ref"]).read_text()
        )
    return Draft202012Validator(schema, format_checker=FormatChecker())


SCHEMA = validator()


def outgoing(
    source: dict[str, Any], producer: str, kind: str, payload: dict[str, Any]
) -> dict[str, Any]:
    try:
        correlation_id = str(UUID(str(source.get("correlation_id"))))
    except ValueError, TypeError, AttributeError:
        correlation_id = str(uuid4())
    try:
        incoming_id = str(UUID(str(source.get("event_id"))))
    except ValueError, TypeError, AttributeError:
        incoming_id = str(uuid4())
    user_id = source.get("user_id")
    if kind == "audit.event" and (current := tracing.trace_id()):
        payload = {**payload, "trace_id": current}
    return {
        "event_id": str(uuid5(NAMESPACE, incoming_id + kind)),
        "type": kind,
        "version": 1,
        "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "correlation_id": correlation_id,
        "user_id": user_id if isinstance(user_id, str) and user_id else "system",
        "producer": producer,
        "payload": payload,
    }


class Bus:
    def __init__(self, config: Config) -> None:
        common = {
            "bootstrap.servers": config.bootstrap,
            "security.protocol": "SASL_PLAINTEXT",
            "sasl.mechanism": "SCRAM-SHA-512",
            "sasl.username": config.username,
            "sasl.password": config.password,
            "log_level": 0,
        }
        self.consumer = Consumer(
            common
            | {
                "group.id": config.name,
                "enable.auto.commit": False,
                "auto.offset.reset": "earliest",
            }
        )
        self.producer = Producer(
            common | {"enable.idempotence": True, "message.timeout.ms": 5000}
        )

    async def publish(self, topic: str, value: dict[str, Any]) -> None:
        SCHEMA.validate(value)
        with tracing.span(
            "send " + topic,
            kind=SpanKind.PRODUCER,
            attributes={
                "messaging.destination.name": topic,
                "messaging.operation.type": "send",
                "ooh.correlation_id": value["correlation_id"],
            },
        ):
            headers = tracing.headers()

            def send() -> None:
                failures = []
                self.producer.produce(
                    topic,
                    key=value["correlation_id"],
                    value=json.dumps(value),
                    headers=headers,
                    on_delivery=lambda error, message: (
                        failures.append(error) if error else None
                    ),
                )
                if self.producer.flush(6) or failures:
                    raise RuntimeError("publish_failed")

            try:
                await asyncio.to_thread(send)
            except KafkaException, BufferError:
                raise RuntimeError("publish_failed") from None


class Processor:
    def __init__(
        self, name: str, bus: Any, handler: Any, sleep: Any = asyncio.sleep
    ) -> None:
        self.name, self.bus, self.handler, self.sleep = name, bus, handler, sleep
        self.seen: set[str] = set()

    async def dlq(
        self, topic: str, raw: bytes, value: dict[str, Any], code: str
    ) -> None:
        if self.name == "safety-watcher" and topic == "chat.messages":
            # Untrusted payloads are never copied into the chat dead-letter topic.
            ids = {
                key: value[key]
                for key in ("event_id", "correlation_id")
                if isinstance(value.get(key), str) and _uuid(value[key])
            }
            message_id = (
                value.get("payload", {}).get("message_id")
                if isinstance(value.get("payload"), dict)
                else None
            )
            if _uuid(message_id):
                ids["message_id"] = message_id
            original = json.dumps(ids)
        else:
            original = raw.decode("utf-8", errors="replace") or "<empty>"
        await self.bus.publish(
            "dlq." + topic,
            outgoing(
                value,
                self.name,
                "dlq.entry",
                {
                    "original_message": original,
                    "error": {"code": code, "message": "Message could not be handled."},
                },
            ),
        )

    async def process(
        self,
        topic: str,
        raw: bytes,
        headers: list[tuple[str, bytes | str | None]] | None = None,
    ) -> None:
        with tracing.span(
            "process " + topic,
            kind=SpanKind.CONSUMER,
            context=tracing.extract(headers),
            attributes={
                "messaging.destination.name": topic,
                "messaging.operation.type": "process",
            },
        ) as current:
            await self._process(topic, raw, current)

    async def _process(self, topic: str, raw: bytes, current: Any) -> None:
        value: dict[str, Any] = {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                value = parsed
            SCHEMA.validate(parsed)
            expected = {
                "audit.events": "audit.event",
                "chat.messages": "chat.message",
                "skill.results": "skill.result",
            }
            if value["type"] != expected[topic]:
                raise ValueError("wrong_type")
        except ValueError, UnicodeDecodeError, ValidationError:
            current.set_attribute("ooh.error_code", "invalid_message")
            current.set_status(Status(StatusCode.ERROR))
            await self.dlq(topic, raw, value, "invalid_message")
            return
        current.set_attribute("ooh.correlation_id", value["correlation_id"])
        current.set_attribute("ooh.user_id", value["user_id"])
        if value["event_id"] in self.seen:
            return
        for attempt in range(4):
            try:
                await self.handler(topic, value)
                self.seen.add(value["event_id"])
                return
            except (
                RuntimeError,
                OSError,
                ValueError,
                KeyError,
                TypeError,
                KafkaException,
            ):
                if attempt == 3:
                    current.set_attribute("ooh.error_code", "handler_failed")
                    current.set_status(Status(StatusCode.ERROR))
                    await self.dlq(topic, raw, value, "handler_failed")
                else:
                    await self.sleep((1, 5, 15)[attempt])


def _uuid(value: Any) -> bool:
    try:
        UUID(value)
        return True
    except ValueError, TypeError, AttributeError:
        return False


class Runner:
    def __init__(
        self,
        bus: Bus,
        processor: Processor,
        topics: list[str],
        exit_process: Any = None,
    ) -> None:
        self.bus, self.processor, self.topics = bus, processor, topics
        self.exit_process = exit_process or os._exit
        self.stopping = False
        self.fatal = False
        self.task: asyncio.Task[None] | None = None

    def stopped(self) -> None:
        self.fatal = True
        logger.error(json.dumps({"message": "consumer_stopped"}))
        self.exit_process(1)

    async def run(self) -> None:
        try:
            self.bus.consumer.subscribe(self.topics)
            while not self.stopping:
                try:
                    message = await asyncio.to_thread(self.bus.consumer.poll, 1)
                    if message is None:
                        continue
                    error = message.error()
                    if error:
                        if error.fatal():
                            raise RuntimeError("consumer_failed")
                        logger.warning(
                            json.dumps(
                                {"message": "consumer_poll_error", "code": error.code()}
                            )
                        )
                        continue
                    await self.processor.process(
                        message.topic(), message.value() or b"", message.headers()
                    )
                    await asyncio.to_thread(
                        self.bus.consumer.commit, message=message, asynchronous=False
                    )
                except KafkaException as error:
                    if not error.args or error.args[0].fatal():
                        raise
                    logger.warning(
                        json.dumps(
                            {
                                "message": "consumer_poll_error",
                                "code": error.args[0].code(),
                            }
                        )
                    )
        except asyncio.CancelledError:
            if not self.stopping:
                self.stopped()
            raise
        except Exception:  # noqa: BLE001 -- Any permanently stopped consumer must restart its process.
            self.stopped()
        finally:
            if not self.fatal:
                try:
                    await asyncio.to_thread(self.bus.consumer.close)
                except Exception:  # noqa: BLE001 -- A shutdown failure must not leave a live, idle API.
                    self.stopped()

    def healthy(self) -> bool:
        return self.task is not None and not self.task.done() and not self.fatal

    async def stop(self) -> None:
        self.stopping = True
        if self.task is not None:
            await self.task
