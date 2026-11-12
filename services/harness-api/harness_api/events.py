# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
import json
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4, uuid5

from confluent_kafka import Consumer, Producer
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from referencing import Registry, Resource

from .config import Settings
from .diagnostics import failure
from .tracing import annotate_event, audit_context, kafka_span

NAMESPACE = UUID("6f1d5b7e-3c1a-4b8e-9a52-1f0c8f3e2d10")


def envelope(
    kind: str,
    correlation: str,
    user: str,
    payload: dict[str, Any],
    incoming: str | None = None,
) -> dict[str, Any]:
    if kind == "audit.event":
        payload = {**payload, **audit_context()}
    return {
        "event_id": str(uuid5(NAMESPACE, incoming + kind) if incoming else uuid4()),
        "type": kind,
        "version": 1,
        "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "correlation_id": correlation,
        "user_id": user,
        "producer": "harness-api",
        "payload": payload,
    }


def validator() -> Draft202012Validator:
    folder = Path(__file__).parent / "event_schemas"
    registry = Registry().with_resources(
        ("payloads/" + path.name, Resource.from_contents(json.loads(path.read_text())))
        for path in (folder / "payloads").glob("*.json")
    )
    return Draft202012Validator(
        json.loads((folder / "envelope.schema.json").read_text()),
        registry=registry,
        format_checker=FormatChecker(),
    )


class Publisher(Protocol):
    async def publish(self, topic: str, event: dict[str, Any]) -> None: ...


class Kafka:
    def __init__(self, settings: Settings) -> None:
        config = {
            "bootstrap.servers": settings.kafka_bootstrap,
            "security.protocol": "SASL_PLAINTEXT",
            "sasl.mechanism": "SCRAM-SHA-512",
            "sasl.username": settings.kafka_username,
            "sasl.password": settings.kafka_password,
            "log_level": 0,
        }
        self.producer = Producer({**config, "message.timeout.ms": 10000})
        self.send_pool = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="harness-kafka-send"
        )
        self.send_slots = asyncio.BoundedSemaphore(4)
        self.consumer_config = {
            **config,
            "group.id": "harness-api",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
        self.consumer = self.new_consumer()
        self.schema = validator()
        self.alive = False

    def new_consumer(self) -> Consumer:
        consumer = Consumer(self.consumer_config)
        consumer.subscribe(["skill.results", "approvals.decided"])
        return consumer

    async def publish(self, topic: str, event: dict[str, Any]) -> None:
        with kafka_span(topic) as headers:
            annotate_event(event)
            await self._publish(topic, event, headers)

    async def _publish(
        self, topic: str, event: dict[str, Any], headers: list[tuple[str, bytes]]
    ) -> None:
        def send() -> None:
            deliveries: list[Any] = []
            delivered = threading.Event()

            def on_delivery(error: Any, message: Any) -> None:
                deliveries.append(error)
                delivered.set()

            self.producer.produce(
                topic,
                key=event["correlation_id"],
                value=json.dumps(event),
                on_delivery=on_delivery,
                headers=headers,
            )
            while not delivered.is_set():
                self.producer.poll(0.1)
            if deliveries != [None]:
                raise RuntimeError("queue_unavailable")

        if topic == "chat.messages" and self.send_slots.locked():
            raise RuntimeError("send_pool_full")
        await self.send_slots.acquire()
        loop = asyncio.get_running_loop()
        try:
            future = self.send_pool.submit(send)
        except Exception:
            self.send_slots.release()
            raise

        def release(done: Future[None]) -> None:
            # Cancellation of the awaiter must not free a still-running send's slot.
            loop.call_soon_threadsafe(self.send_slots.release)

        future.add_done_callback(release)
        await asyncio.wrap_future(future)

    async def close(self) -> None:
        await asyncio.to_thread(self.send_pool.shutdown, wait=True, cancel_futures=True)

    async def serve(
        self,
        handle: Callable[[str, dict[str, Any]], Awaitable[None]],
        stop: asyncio.Event,
    ) -> None:
        rebuild = False
        while not stop.is_set():
            try:
                if rebuild:
                    self.consumer = await asyncio.to_thread(self.new_consumer)
                await self.run(handle, stop)
            except Exception:
                failure("kafka_error", "consumer_stopped")
            if not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=5)
                except TimeoutError:
                    pass
            rebuild = True

    async def run(
        self,
        handle: Callable[[str, dict[str, Any]], Awaitable[None]],
        stop: asyncio.Event,
    ) -> None:
        self.alive = True
        try:
            while not stop.is_set():
                message = await asyncio.to_thread(self.consumer.poll, 1)
                if message is None:
                    continue
                error = message.error()
                if error:
                    if error.fatal():
                        raise RuntimeError("consumer_error")
                    failure("kafka_error", "consumer_poll_error")
                    continue
                with kafka_span(message.topic(), message.headers() or []):
                    raw = message.value().decode("utf-8", errors="replace")
                    event: dict[str, Any] = {}
                    try:
                        event = json.loads(raw)
                        annotate_event(event)
                        self.schema.validate(event)
                        expected = {
                            "skill.results": "skill.result",
                            "approvals.decided": "approval.decided",
                        }
                        if event["type"] != expected[message.topic()]:
                            raise ValueError("wrong_type")
                    except ValueError, ValidationError:
                        await self.dead_letter(
                            message.topic(), raw, event, "bad_message"
                        )
                    else:
                        for attempt in range(4):
                            try:
                                await handle(message.topic(), event)
                                break
                            except Exception:
                                if attempt == 3:
                                    await self.dead_letter(
                                        message.topic(), raw, event, "handling_failed"
                                    )
                                else:
                                    await asyncio.sleep((1, 5, 15)[attempt])
                await asyncio.to_thread(
                    self.consumer.commit, message=message, asynchronous=False
                )
        finally:
            self.alive = False
            await asyncio.to_thread(self.consumer.close)

    async def dead_letter(self, topic: str, raw: str, event: Any, code: str) -> None:
        readable = event if isinstance(event, dict) else {}
        try:
            correlation = str(UUID(readable.get("correlation_id", "")))
        except ValueError, TypeError, AttributeError:
            correlation = str(uuid4())
        user = readable.get("user_id")
        if not isinstance(user, str) or not user:
            user = "system"
        incoming = readable.get("event_id")
        if not isinstance(incoming, str):
            incoming = None
        await self.publish(
            "dlq." + topic,
            envelope(
                "dlq.entry",
                correlation,
                user,
                {
                    "original_message": raw,
                    "error": {
                        "code": code,
                        "message": "The event could not be handled.",
                    },
                },
                incoming,
            ),
        )


class JobEvents:
    def __init__(self) -> None:
        self.subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}

    def emit(self, user: str, event: dict[str, Any]) -> None:
        for queue in self.subscribers.get(user, set()):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)
