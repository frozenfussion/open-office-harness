# SPDX-License-Identifier: AGPL-3.0-only
import json
import logging
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
        self.producer = Producer(config)
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
        errors: list[Any] = []
        self.producer.produce(
            topic,
            key=event["correlation_id"],
            value=json.dumps(event),
            on_delivery=lambda error, message: errors.append(error) if error else None,
        )
        if self.producer.flush(10) or errors:
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
                if message.error():
                    raise RuntimeError("consumer_error")
                self.worker.process(message.value().decode("utf-8", errors="replace"))
                self.kafka.consumer.commit(message=message, asynchronous=False)
        except Exception:
            self.fatal = True
            logging.getLogger("slides").error("consumer_stopped")
        finally:
            self.kafka.consumer.close()

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
            checks = Path(settings.files_root) / "checks"
            checks.mkdir(mode=0o755, exist_ok=True)
            (checks / "slides-worker-health").write_text("ok\n")
        except OSError:
            return JSONResponse({"status": "down"}, status_code=503)
        return JSONResponse({"status": "ok"})

    return app


def factory() -> FastAPI:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return create_app(Settings.from_env())
