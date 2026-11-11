# SPDX-License-Identifier: AGPL-3.0-only
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pptx import Presentation

from slides_worker.app import Runtime, create_app
from slides_worker.config import Settings
from slides_worker.worker import MAX_POLL_INTERVAL_MS, Worker


class Publisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def publish(self, topic: str, event: dict[str, Any]) -> None:
        self.events.append((topic, event))


class Model:
    def __init__(self) -> None:
        self.calls = 0
        self.output = json.dumps(
            {
                "title": "Water cycle",
                "subtitle": "Example",
                "slides": [
                    {"title": "Stage", "bullets": ["Example bullet"]} for _ in range(3)
                ],
            }
        )
        self.fail = False

    def call(self, event: dict[str, Any], correction: str | None) -> str:
        self.calls += 1
        if self.fail:
            raise RuntimeError("synthetic failure")
        return self.output


def request(**payload: Any) -> dict[str, Any]:
    return {
        "event_id": str(uuid4()),
        "correlation_id": str(uuid4()),
        "type": "skill.requested",
        "version": 1,
        "occurred_at": "2026-11-11T00:00:00Z",
        "producer": "harness-api",
        "user_id": "test-user",
        "payload": {
            "skill": "slides",
            "skill_version": "1.0.0",
            "input": {"topic": "Example"},
            **payload,
        },
    }


def test_deck_replay_schema_and_tokens(tmp_path: Path) -> None:
    model, publisher = Model(), Publisher()
    worker = Worker(str(tmp_path), model, publisher)
    event = request()
    worker.process(json.dumps(event))
    result = publisher.events[0][1]
    path = tmp_path / result["payload"]["output"]["file_key"]
    deck = Presentation(str(path))
    assert len(deck.slides) == 4
    assert deck.slide_width / deck.slide_height == pytest.approx(16 / 9)
    modified = path.stat().st_mtime_ns
    worker.process(json.dumps(event))
    assert model.calls == 1 and path.stat().st_mtime_ns == modified
    assert publisher.events[2][1]["event_id"] == result["event_id"]
    root = Path(__file__).resolve().parents[3]
    package = Path(__file__).parents[1] / "slides_worker"
    assert json.loads(
        (root / "contracts/skills/slides/input.schema.json").read_text()
    ) == json.loads((package / "schemas/input.json").read_text())
    assert json.loads(
        (root / "apps/design-system/tokens.json").read_text()
    ) == json.loads((package / "tokens.json").read_text())
    for _, published in publisher.events:
        worker.schema.validate(published)


@pytest.mark.parametrize(
    "payload,code",
    [({"input": {}}, "bad_input"), ({"skill": "unknown"}, "unknown_skill")],
)
def test_input_refused(tmp_path: Path, payload: dict[str, Any], code: str) -> None:
    model, publisher = Model(), Publisher()
    Worker(str(tmp_path), model, publisher).process(json.dumps(request(**payload)))
    assert publisher.events[0][1]["payload"]["error"]["code"] == code
    assert model.calls == 0


def test_bad_model_twice(tmp_path: Path) -> None:
    model, publisher = Model(), Publisher()
    model.output = "invalid JSON"
    Worker(str(tmp_path), model, publisher).process(json.dumps(request()))
    assert model.calls == 2
    assert publisher.events[0][1]["payload"]["error"]["code"] == "bad_model_output"


def test_retries_and_dead_letter(tmp_path: Path) -> None:
    model, publisher, waits = Model(), Publisher(), []
    model.fail = True
    worker = Worker(str(tmp_path), model, publisher, sleep=waits.append)
    worker.process(json.dumps(request()))
    assert model.calls == 4 and waits == [1, 5, 15]
    assert [topic for topic, _ in publisher.events] == [
        "dlq.skill.requests.slides",
        "skill.results",
        "audit.events",
    ]
    assert publisher.events[1][1]["payload"]["error"]["code"] == "worker_gave_up"
    publisher.events.clear()
    worker.process("not json")
    assert [topic for topic, _ in publisher.events] == ["dlq.skill.requests.slides"]
    worker.schema.validate(publisher.events[0][1])


def test_slow_gateway_poll_budget_and_health(tmp_path: Path) -> None:
    model, publisher = Model(), Publisher()
    elapsed = [0]

    def slow(event: dict[str, Any], correction: str | None) -> str:
        elapsed[0] += 910
        model.calls += 1
        if correction:
            raise RuntimeError("synthetic timeout")
        return "invalid JSON"

    model.call = slow
    worker = Worker(
        str(tmp_path),
        model,
        publisher,
        sleep=lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds),
    )
    event = request()

    class Message:
        def value(self) -> bytes:
            return json.dumps(event).encode()

        def error(self) -> None:
            return None

    class Consumer:
        commits = 0
        polls = 0

        def poll(self, timeout: float) -> Message:
            self.polls += 1
            assert elapsed[0] * 1000 < MAX_POLL_INTERVAL_MS
            return Message()

        def commit(self, **kwargs: Any) -> None:
            self.commits += 1
            runtime.stop.set()

        def close(self) -> None:
            pass

    class Kafka:
        consumer = Consumer()

    kafka = Kafka()
    runtime = Runtime(worker, kafka)
    runtime.run()
    assert kafka.consumer.polls == kafka.consumer.commits == 1
    assert model.calls == 8 and elapsed[0] == 7301
    assert MAX_POLL_INTERVAL_MS == 7400000

    class Thread:
        def is_alive(self) -> bool:
            return True

    runtime.thread = Thread()
    assert runtime.healthy()
    runtime.fatal = True
    assert not runtime.healthy()


@pytest.mark.anyio
async def test_health_fixed_file(tmp_path: Path) -> None:
    class Healthy:
        def healthy(self) -> bool:
            return True

    settings = Settings(
        "unused",
        "unused",
        "synthetic",
        "https://identity.invalid",
        "worker",
        "synthetic",
        "http://gateway.invalid",
        str(tmp_path),
    )
    (tmp_path / "checks").write_text("unavailable platform check path")
    app = create_app(settings, Healthy())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://worker.test"
    ) as client:
        for _ in range(2):
            assert (await client.get("/health")).status_code == 200
    assert [path.name for path in (tmp_path / "outputs/slides").iterdir()] == [
        ".health"
    ]
    assert (tmp_path / "checks").read_text() == "unavailable platform check path"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_gateway_contract_and_timeout() -> None:
    from slides_worker.worker import Gateway

    settings = Settings(
        "unused",
        "unused",
        "synthetic",
        "https://identity.invalid",
        "worker",
        "synthetic",
        "http://gateway.invalid",
    )
    event = request()
    calls = []

    def send(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/token"):
            return httpx.Response(
                200, json={"access_token": "synthetic-token", "expires_in": 300}
            )
        body = json.loads(request.content)
        assert body["user_id"] == event["user_id"] and body["stream"] is False
        assert request.headers["X-Correlation-Id"] == event["correlation_id"]
        assert request.extensions["timeout"]["read"] == 910
        return httpx.Response(200, json={"content": "{}"})

    with httpx.Client(transport=httpx.MockTransport(send)) as client:
        gateway = Gateway(settings, client)
        assert gateway.call(event, None) == "{}"
        assert gateway.call(event, "Expected JSON") == "{}"
    assert len(calls) == 3


@pytest.mark.parametrize("fence", ["```json", "```", "  ```json  "])
def test_fenced_json_needs_one_model_call(tmp_path: Path, fence: str) -> None:
    model, publisher = Model(), Publisher()
    model.output = " \n" + fence + "\n" + model.output + "\n```\n "
    Worker(str(tmp_path), model, publisher).process(json.dumps(request()))
    assert model.calls == 1
    assert publisher.events[0][1]["payload"]["status"] == "completed"


@pytest.mark.parametrize("failure", ["none", "fatal", "publish", "close"])
def test_consumer_nonfatal_errors_and_process_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: str,
) -> None:
    import slides_worker.app as module

    model, publisher = Model(), Publisher()
    worker = Worker(str(tmp_path), model, publisher)
    processed = []

    def process(raw: str) -> None:
        processed.append(raw)
        if failure == "publish":
            raise RuntimeError("synthetic publish failure")

    monkeypatch.setattr(worker, "process", process)

    class Error:
        def fatal(self) -> bool:
            return failure == "fatal"

    class Message:
        def __init__(self, error: Error | None) -> None:
            self.poll_error = error

        def error(self) -> Error | None:
            return self.poll_error

        def value(self) -> bytes:
            return b"synthetic"

    class Consumer:
        def __init__(self) -> None:
            self.messages = [Message(Error()), Message(None)]
            self.closed = False
            self.commits = 0

        def poll(self, seconds: int) -> Message:
            return self.messages.pop(0)

        def commit(self, **kwargs: Any) -> None:
            self.commits += 1
            runtime.stop.set()

        def close(self) -> None:
            self.closed = True
            if failure == "close":
                raise RuntimeError("synthetic close failure")

    class Kafka:
        consumer = Consumer()

    kafka = Kafka()
    runtime = Runtime(worker, kafka)
    exits = []
    monkeypatch.setattr(module.os, "_exit", exits.append)
    monkeypatch.setattr(module.logging, "shutdown", lambda: None)
    runtime.run()
    assert kafka.consumer.closed
    if failure == "none":
        assert processed == ["synthetic"] and kafka.consumer.commits == 1
        assert exits == [] and not runtime.fatal
        assert any(record.message == "consumer_poll_error" for record in caplog.records)
    else:
        assert exits == [1] and runtime.fatal
        assert any(
            getattr(record, "event", "") == "consumer_stopped"
            for record in caplog.records
        )
        assert kafka.consumer.commits == (1 if failure == "close" else 0)


@pytest.mark.parametrize("mode", ["success", "timeout", "delayed"])
def test_worker_producer_waits_for_own_callback(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    import slides_worker.app as module

    class Producer:
        def __init__(self, config: dict[str, Any]) -> None:
            assert config["message.timeout.ms"] == 10000
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
            if mode == "delayed" and self.polls < 3:
                self.foreign_deliveries.append(RuntimeError("another message failed"))
                return
            self.pending = False
            self.callback(None if mode != "timeout" else RuntimeError("timeout"), None)

        def purge(self, **kwargs: Any) -> None:
            pytest.fail("A publish must not purge other messages")

    class Consumer:
        def __init__(self, config: dict[str, Any]) -> None:
            pass

        def subscribe(self, topics: list[str]) -> None:
            assert topics == ["skill.requests.slides"]

    monkeypatch.setattr(module, "Producer", Producer)
    monkeypatch.setattr(module, "Consumer", Consumer)
    settings = Settings(
        "unused",
        "unused",
        "synthetic",
        "https://identity.invalid",
        "worker",
        "synthetic",
        "http://gateway.invalid",
    )
    kafka = module.Kafka(settings)
    if mode != "timeout":
        kafka.publish("skill.results", {"correlation_id": str(uuid4())})
    else:
        with pytest.raises(RuntimeError, match="queue_unavailable"):
            kafka.publish("skill.results", {"correlation_id": str(uuid4())})
    assert not kafka.producer.pending
    assert kafka.producer.polls == (3 if mode == "delayed" else 1)
