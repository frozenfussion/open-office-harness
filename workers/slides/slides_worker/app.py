# SPDX-License-Identifier: AGPL-3.0-only
import json
import logging
import os
import sys
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from confluent_kafka import Consumer, Producer
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .config import Settings
from .diagnostics import JsonFormatter
from .tracing import annotate_event, instrument, kafka_span
from .worker import MAX_POLL_INTERVAL_MS, Gateway, Worker


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
        self.consumer = Consumer(
            {
                **config,
                "group.id": "slides-worker",
                "enable.auto.commit": False,
                "auto.offset.reset": "earliest",
                "max.poll.interval.ms": MAX_POLL_INTERVAL_MS,
            }
        )
        self.consumer.subscribe(["skill.requests.slides"])

    def publish(self, topic: str, event: dict[str, Any]) -> None:
        with kafka_span(topic) as headers:
            annotate_event(event)
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


class Runtime:
    def __init__(self, worker: Worker, kafka: Kafka) -> None:
        self.worker, self.kafka = worker, kafka
        self.stop = threading.Event()
        self.fatal = False
        self.thread = threading.Thread(target=self.run, name="slides-consumer")

    def run(self) -> None:
        try:
            while not self.stop.is_set():
                message = self.kafka.consumer.poll(1)
                if message is None:
                    continue
                error = message.error()
                if error:
                    if error.fatal():
                        raise RuntimeError("consumer_error")
                    logging.getLogger("slides").warning(
                        "consumer_poll_error",
                        extra={"event": "consumer_poll_error", "code": "unavailable"},
                    )
                    continue
                with kafka_span(message.topic(), message.headers() or []):
                    self.worker.process(
                        message.value().decode("utf-8", errors="replace")
                    )
                self.kafka.consumer.commit(message=message, asynchronous=False)
        except Exception:
            self.fatal = True
        finally:
            try:
                self.kafka.consumer.close()
            except Exception:
                self.fatal = True
            if self.fatal or not self.stop.is_set():
                logging.getLogger("slides").error(
                    "consumer_stopped",
                    extra={"event": "consumer_stopped", "code": "unavailable"},
                )
                logging.shutdown()
                os._exit(1)

    def healthy(self) -> bool:
        return self.thread.is_alive() and not self.fatal


def create_app(settings: Settings, runtime: Runtime | None = None) -> FastAPI:
    client = httpx.Client(follow_redirects=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal runtime
        if runtime is None:
            kafka = Kafka(settings)
            runtime = Runtime(
                Worker(settings.files_root, Gateway(settings, client), kafka), kafka
            )
        runtime.thread.start()
        try:
            yield
        finally:
            runtime.stop.set()
            # The Kubernetes grace period covers the longest in-flight job.
            import asyncio

            await asyncio.to_thread(runtime.thread.join)
            await asyncio.to_thread(client.close)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    def health() -> JSONResponse:
        try:
            if runtime is None or not runtime.healthy():
                raise OSError("consumer_unavailable")
            outputs = Path(settings.files_root) / "outputs/slides"
            outputs.mkdir(mode=0o755, parents=True, exist_ok=True)
            (outputs / ".health").write_text("ok\n")
        except OSError:
            return JSONResponse({"status": "down"}, status_code=503)
        return JSONResponse({"status": "ok"})

    instrument(app, client)
    return app


def factory() -> FastAPI:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return create_app(Settings.from_env())
