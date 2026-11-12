# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
import json
import threading
from dataclasses import replace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from conftest import SETTINGS, Harness
from starlette.requests import Request
from test_routes import events

import harness_api.app as app_module
import harness_api.events as kafka_module
from harness_api.events import Kafka, envelope

pytestmark = pytest.mark.anyio


class PollError:
    def __init__(self, fatal: bool) -> None:
        self.is_fatal = fatal

    def fatal(self) -> bool:
        return self.is_fatal


class Message:
    def __init__(self, content: str = "", error: PollError | None = None) -> None:
        self.content, self.poll_error = content, error

    def error(self) -> PollError | None:
        return self.poll_error

    def value(self) -> bytes:
        return self.content.encode()

    def headers(self) -> list[tuple[str, bytes]]:
        return []

    def topic(self) -> str:
        return "skill.results"


class Consumer:
    def __init__(self, messages: list[Message], stop: asyncio.Event) -> None:
        self.messages, self.stop = messages, stop
        self.closed = False
        self.commits = 0

    def subscribe(self, topics: list[str]) -> None:
        assert topics == ["skill.results", "approvals.decided"]

    def poll(self, timeout: int) -> Message:
        return self.messages.pop(0)

    def commit(self, **kwargs: Any) -> None:
        self.commits += 1
        if not self.messages:
            self.stop.set()

    def close(self) -> None:
        self.closed = True


def result() -> Message:
    return Message(
        json.dumps(
            envelope(
                "skill.result",
                str(uuid4()),
                "test-user",
                {
                    "skill": "slides",
                    "status": "failed",
                    "output": None,
                    "error": {"code": "example", "message": "Example"},
                },
            )
        )
    )


async def test_nonfatal_poll_keeps_consuming(monkeypatch: pytest.MonkeyPatch) -> None:
    stop = asyncio.Event()
    consumer = Consumer([Message(error=PollError(False)), result()], stop)
    monkeypatch.setattr(kafka_module, "Consumer", lambda config: consumer)
    monkeypatch.setattr(kafka_module, "Producer", lambda config: None)
    kafka = Kafka(SETTINGS)
    handled = []

    async def handle(topic: str, event: dict[str, Any]) -> None:
        handled.append(event)

    await kafka.run(handle, stop)
    assert len(handled) == consumer.commits == 1 and consumer.closed


@pytest.mark.parametrize("cause", ["fatal", "dlq"])
async def test_stopped_consumer_rebuilt_after_five_seconds(
    monkeypatch: pytest.MonkeyPatch,
    cause: str,
) -> None:
    stop = asyncio.Event()
    first = Consumer(
        [Message(error=PollError(True))] if cause == "fatal" else [Message("not json")],
        stop,
    )
    second = Consumer([result()], stop)
    consumers = [first, second]
    created = []

    def create(config: dict[str, Any]) -> Consumer:
        created.append(config)
        return consumers.pop(0)

    monkeypatch.setattr(kafka_module, "Consumer", create)
    monkeypatch.setattr(kafka_module, "Producer", lambda config: None)
    kafka = Kafka(SETTINGS)

    async def fail_publish(*args: Any) -> None:
        raise RuntimeError("synthetic broker outage")

    monkeypatch.setattr(kafka, "publish", fail_publish)
    waits = []

    async def wait(awaitable: Any, **kwargs: Any) -> None:
        waits.append(kwargs["timeout"])
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", wait)
    handled = []

    async def handle(topic: str, event: dict[str, Any]) -> None:
        handled.append(event)

    await kafka.serve(handle, stop)
    assert waits == [5] and len(created) == 2
    assert first.closed and first.commits == 0
    assert second.closed and second.commits == len(handled) == 1


async def test_health_depends_only_on_database(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "Kafka", lambda settings: object())
    app = app_module.create_app(
        replace(SETTINGS, kafka_bootstrap="synthetic"), store=h.store, client=h.http
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://harness.test"
    ) as client:
        assert (await client.get("/health")).status_code == 200
        h.store.fail_health = True
        assert (await client.get("/health")).status_code == 503


class Producer:
    def __init__(self, config: dict[str, Any], mode: str) -> None:
        assert config["message.timeout.ms"] == 10000
        self.mode = mode
        self.callback: Any = None
        self.pending = False
        self.polls = 0
        self.foreign_deliveries: list[Any] = []

    def produce(self, topic: str, **kwargs: Any) -> None:
        self.callback = kwargs["on_delivery"]
        self.pending = True

    def poll(self, seconds: float) -> None:
        assert seconds == 0.1
        self.polls += 1
        if self.mode == "delayed" and self.polls < 3:
            self.foreign_deliveries.append(RuntimeError("another message failed"))
            return
        self.pending = False
        self.callback(None if self.mode != "timeout" else RuntimeError("timeout"), None)

    def purge(self, **kwargs: Any) -> None:
        pytest.fail("A publish must not purge other messages")


@pytest.mark.parametrize("mode", ["success", "timeout", "delayed"])
async def test_producer_waits_for_own_delivery_callback(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    producers = []

    def producer(config: dict[str, Any]) -> Producer:
        instance = Producer(config, mode)
        producers.append(instance)
        return instance

    monkeypatch.setattr(kafka_module, "Producer", producer)
    monkeypatch.setattr(
        kafka_module, "Consumer", lambda config: Consumer([], asyncio.Event())
    )
    kafka = Kafka(SETTINGS)
    try:
        if mode != "timeout":
            await kafka.publish(
                "skill.requests.slides", {"correlation_id": str(uuid4())}
            )
        else:
            with pytest.raises(RuntimeError, match="queue_unavailable"):
                await kafka.publish(
                    "skill.requests.slides", {"correlation_id": str(uuid4())}
                )
        assert not producers[0].pending
        assert producers[0].polls == (3 if mode == "delayed" else 1)
    finally:
        await kafka.close()


async def test_hanging_publish_never_delays_chat(
    h: Harness,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    identifier = await h.conversation()
    entered = asyncio.Event()

    async def hang(*args: Any) -> None:
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(h.publisher, "publish", hang)
    monkeypatch.setattr(app_module, "CHAT_PUBLISH_TIMEOUT_SECONDS", 0.01)
    response = await asyncio.wait_for(h.send(identifier), timeout=1)
    assert events(response)[-1]["type"] == "completed"
    await entered.wait()
    await asyncio.gather(*h.app.state.chat_tasks)
    failures = [
        record
        for record in caplog.records
        if getattr(record, "code", "") == "chat_publish_failed"
    ]
    assert len(failures) == 2
    assert all(getattr(record, "correlation_id", None) for record in failures)
    assert not h.app.state.chat_tasks


async def test_event_stream_closes_at_expiry(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [100.0]
    monkeypatch.setattr(app_module.time, "time", lambda: clock[0])
    route = next(route for route in h.app.routes if route.path == "/api/events")
    response = await route.endpoint(
        Request({"type": "http", "query_string": b""}), {"sub": "test-user", "exp": 101}
    )

    async def wait(awaitable: Any, **kwargs: Any) -> None:
        assert kwargs["timeout"] == 1
        awaitable.close()
        clock[0] = 101
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", wait)
    with pytest.raises(StopAsyncIteration):
        await anext(response.body_iterator)
    assert h.app.state.notifications.subscribers == {}


async def test_simultaneous_publishes_use_their_own_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = threading.Event()
    callbacks: dict[str, Any] = {}
    lock = threading.Lock()
    first, second = str(uuid4()), str(uuid4())

    class ConcurrentProducer:
        def __init__(self, config: dict[str, Any]) -> None:
            assert config["message.timeout.ms"] == 10000

        def produce(self, topic: str, **kwargs: Any) -> None:
            with lock:
                callbacks[kwargs["key"]] = kwargs["on_delivery"]
                if len(callbacks) == 2:
                    ready.set()

        def poll(self, seconds: float) -> None:
            assert ready.wait(2), "Both sends must start independently"
            with lock:
                if callbacks:
                    callbacks.pop(second)(RuntimeError("second message failed"), None)
                    callbacks.pop(first)(None, None)

        def purge(self, **kwargs: Any) -> None:
            pytest.fail("A failed send must not purge another send")

    monkeypatch.setattr(kafka_module, "Producer", ConcurrentProducer)
    monkeypatch.setattr(
        kafka_module, "Consumer", lambda config: Consumer([], asyncio.Event())
    )
    kafka = Kafka(SETTINGS)
    try:
        outcomes = await asyncio.gather(
            kafka.publish("skill.requests.slides", {"correlation_id": first}),
            kafka.publish("audit.events", {"correlation_id": second}),
            return_exceptions=True,
        )
        assert outcomes[0] is None
        assert isinstance(outcomes[1], RuntimeError)
        assert str(outcomes[1]) == "queue_unavailable"
    finally:
        await kafka.close()


async def test_full_send_pool_skips_chat_and_keeps_consumer_available(
    h: Harness,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    lock = threading.Lock()
    callbacks: list[Any] = []
    threads: list[str] = []

    class BlockedProducer:
        def __init__(self, config: dict[str, Any]) -> None:
            assert config["message.timeout.ms"] == 10000

        def produce(self, topic: str, **kwargs: Any) -> None:
            with lock:
                threads.append(threading.current_thread().name)
                callbacks.append(kwargs["on_delivery"])
                if len(threads) == 4:
                    loop.call_soon_threadsafe(started.set)

        def poll(self, seconds: float) -> None:
            assert release.wait(3), "The test must release the blocked sends"
            with lock:
                pending = callbacks.copy()
                callbacks.clear()
            for callback in pending:
                callback(None, None)

    stop = asyncio.Event()
    consumer = Consumer([result()], stop)
    monkeypatch.setattr(kafka_module, "Consumer", lambda config: consumer)
    monkeypatch.setattr(kafka_module, "Producer", BlockedProducer)
    kafka = Kafka(SETTINGS)
    sends = [
        asyncio.create_task(
            kafka.publish("chat.messages", {"correlation_id": str(uuid4())})
        )
        for _ in range(4)
    ]
    job = None
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        assert all(name.startswith("harness-kafka-send") for name in threads)
        # Cancelling chat awaiters must not make their still-running threads available.
        for send in sends:
            send.cancel()
        await asyncio.gather(*sends, return_exceptions=True)
        assert kafka.send_slots.locked()
        handled = []

        async def handle(topic: str, event: dict[str, Any]) -> None:
            handled.append(event)

        await asyncio.wait_for(kafka.run(handle, stop), timeout=1)
        assert consumer.commits == len(handled) == 1
        monkeypatch.setattr(h.publisher, "publish", kafka.publish)
        identifier = await h.conversation()
        response = await asyncio.wait_for(h.send(identifier), timeout=1)
        assert events(response)[-1]["type"] == "completed"
        await asyncio.gather(*h.app.state.chat_tasks)
        assert len(threads) == 4  # No chat message was queued behind the blocked sends.
        assert (
            sum(
                getattr(record, "code", "") == "chat_publish_failed"
                for record in caplog.records
            )
            == 2
        )
        job = asyncio.create_task(
            kafka.publish("skill.requests.slides", {"correlation_id": str(uuid4())})
        )
        await asyncio.sleep(0)
        assert not job.done() and len(threads) == 4
        release.set()
        await asyncio.wait_for(job, timeout=1)
        assert len(threads) == 5
    finally:
        release.set()
        for send in sends:
            send.cancel()
        await asyncio.gather(*sends, return_exceptions=True)
        if job is not None:
            await job
        await kafka.close()
