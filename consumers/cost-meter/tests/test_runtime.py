# SPDX-License-Identifier: AGPL-3.0-only
import json
from typing import Any

import pytest
from confluent_kafka import KafkaError, KafkaException

from consumer.events import Runner


class Message:
    def __init__(self, error: Any = None) -> None:
        self.problem = error

    def error(self) -> Any:
        return self.problem

    def topic(self) -> str:
        return "audit.events"

    def headers(self) -> list[tuple[str, bytes]]:
        return []

    def value(self) -> bytes:
        return b"synthetic"


class Kafka:
    def __init__(self, messages: list[Any]) -> None:
        self.messages = iter(messages)
        self.commits = 0
        self.closed = False

    def subscribe(self, topics: list[str]) -> None:
        pass

    def poll(self, timeout: int) -> Any:
        value = next(self.messages)
        if isinstance(value, BaseException):
            raise value
        return value

    def commit(self, **kwargs: Any) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True


@pytest.mark.anyio
@pytest.mark.parametrize("raised", [False, True])
async def test_nonfatal_kafka_error_logged_and_polling_continues(
    raised: bool, caplog: pytest.LogCaptureFixture
) -> None:
    error = KafkaError(
        KafkaError._TRANSPORT, "synthetic-private-diagnostic", fatal=False
    )
    kafka = Kafka([KafkaException(error) if raised else Message(error), Message()])
    handled, exits = [], []

    class Handler:
        async def process(self, topic: str, raw: bytes, headers: Any = None) -> None:
            handled.append(raw)
            runner.stopping = True

    class Bus:
        consumer = kafka

    runner = Runner(Bus(), Handler(), ["audit.events"], exit_process=exits.append)
    await runner.run()
    assert handled == [b"synthetic"] and kafka.commits == 1 and kafka.closed
    assert exits == [] and not runner.fatal
    assert (
        "consumer_poll_error" in caplog.text
        and "synthetic-private-diagnostic" not in caplog.text
    )


@pytest.mark.anyio
@pytest.mark.parametrize("cause", ["fatal_poll", "dlq_failure"])
async def test_permanently_stopped_consumer_exits_one_after_logging(
    cause: str, caplog: pytest.LogCaptureFixture
) -> None:
    error = KafkaError(KafkaError._FATAL, "synthetic-private-diagnostic", fatal=True)
    kafka = Kafka([Message(error) if cause == "fatal_poll" else Message()])
    exits = []

    class Handler:
        async def process(self, topic: str, raw: bytes, headers: Any = None) -> None:
            raise RuntimeError("synthetic-private-dlq-error")

    class Bus:
        consumer = kafka

    def exit_process(code: int) -> None:
        assert any(
            json.loads(record.message).get("message") == "consumer_stopped"
            for record in caplog.records
        )
        exits.append(code)

    runner = Runner(Bus(), Handler(), ["audit.events"], exit_process=exit_process)
    await runner.run()
    assert exits == [1] and runner.fatal and not runner.healthy()
    assert kafka.commits == 0
    assert "synthetic-private" not in caplog.text
