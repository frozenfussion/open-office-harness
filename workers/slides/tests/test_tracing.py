# SPDX-License-Identifier: AGPL-3.0-only
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from slides_worker import tracing
from slides_worker.worker import envelope


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Any, Any]]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(
        SimpleSpanProcessor(tracing.FilteringExporter(exporter))
    )
    monkeypatch.setattr(tracing, "provider", provider)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://unused.test")
    yield provider.get_tracer("test"), exporter
    provider.shutdown()


def test_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.setattr(tracing, "provider", None)
    assert tracing.configure() is None
    assert tracing.provider is None
    assert tracing.audit_context() == {}
    assert (
        "trace_id"
        not in envelope(
            "audit.event",
            {"event_id": "id", "user_id": "user", "correlation_id": "id"},
            {},
        )["payload"]
    )
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    assert tracing.configure() is None


def test_schema_copies() -> None:
    root = Path(__file__).resolve().parents[3]
    package = Path(__file__).parents[1] / "slides_worker/schemas"
    for name in ["envelope.schema.json", "payloads/audit.event.schema.json"]:
        assert (package / name).read_bytes() == (
            root / "contracts/events" / name
        ).read_bytes()


def test_kafka_parent_and_filter(spans: Any) -> None:
    tracer, exporter = spans
    with tracer.start_as_current_span(
        "request",
        context=tracing.propagator.extract(
            {
                "traceparent": "00-" + "3" * 32 + "-" + "4" * 16 + "-01",
                "tracestate": "test=demo",
            }
        ),
    ) as parent:
        with tracing.kafka_span("skill.requests.slides") as headers:
            assert dict(headers)["traceparent"].decode().split("-")[1] == format(
                parent.get_span_context().trace_id, "032x"
            )
        assert dict(headers)["tracestate"] == b"test=demo"
        with tracing.kafka_span("skill.requests.slides", headers):
            assert (
                trace.get_current_span().get_span_context().trace_state.to_header()
                == "test=demo"
            )
            audit = envelope(
                "audit.event",
                {"event_id": "id", "user_id": "user", "correlation_id": "id"},
                {},
            )
            assert audit["payload"]["trace_id"] == format(
                parent.get_span_context().trace_id, "032x"
            )
    published, consumed, root = exporter.get_finished_spans()
    assert consumed.parent.span_id == published.context.span_id
    assert published.parent.span_id == root.context.span_id
    assert published.kind == trace.SpanKind.PRODUCER
    assert consumed.kind == trace.SpanKind.CONSUMER


@pytest.mark.anyio
async def test_http_roots_children_and_private_errors(spans: Any) -> None:
    tracer, exporter = spans
    app = FastAPI()
    internal = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200))
    )

    @app.get("/sample/{identifier}")
    async def sample(identifier: str) -> dict[str, str]:
        await internal.get("http://service.test/rights?private=PRIVATE_MARKER")
        return tracing.audit_context()

    @app.get("/broken")
    async def broken() -> None:
        raise RuntimeError("PRIVATE_MARKER")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {}

    tracing.instrument(app, internal)
    incoming = "00-" + "1" * 32 + "-" + "2" * 16 + "-01"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://app.test",
    ) as client:
        first = await client.get(
            "/sample/PRIVATE_MARKER?secret=PRIVATE_MARKER",
            headers={"traceparent": incoming},
        )
        assert first.json()["trace_id"] == "1" * 32
        assert (await client.get("/broken")).status_code == 500
        before = len(exporter.get_finished_spans())
        await client.get("/health")
        assert len(exporter.get_finished_spans()) == before
    await internal.aclose()
    finished = exporter.get_finished_spans()
    assert any(s.kind == trace.SpanKind.CLIENT and s.parent for s in finished)
    assert any(s.status.status_code == trace.StatusCode.ERROR for s in finished)
    for span in finished:
        assert not span.events
        assert set(span.attributes) <= tracing.ALLOWED
        assert "PRIVATE_MARKER" not in str(
            (span.name, dict(span.attributes), span.status.description)
        )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_runtime_consumer_gateway_and_real_producer(spans: Any, tmp_path: Path) -> None:
    import json

    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from test_worker import request

    from slides_worker.app import Kafka, Runtime
    from slides_worker.config import Settings
    from slides_worker.worker import Gateway, Worker

    tracer, exporter = spans
    event = request()
    with tracer.start_as_current_span("request"):
        with tracing.kafka_span("skill.requests.slides") as incoming:
            pass
    sent = []

    class Producer:
        def produce(self, topic: str, **kwargs: Any) -> None:
            sent.append((topic, kwargs))
            kwargs["on_delivery"](None, None)

    class Message:
        def headers(self) -> Any:
            return incoming

        def topic(self) -> str:
            return "skill.requests.slides"

        def value(self) -> bytes:
            return json.dumps(event).encode()

        def error(self) -> None:
            return None

    class Consumer:
        def poll(self, seconds: int) -> Message:
            return Message()

        def commit(self, **kwargs: Any) -> None:
            runtime.stop.set()

        def close(self) -> None:
            pass

    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/token"):
            return httpx.Response(
                200, json={"access_token": "synthetic", "expires_in": 300}
            )
        return httpx.Response(
            200,
            json={
                "content": json.dumps(
                    {
                        "title": "Example",
                        "subtitle": "",
                        "slides": [
                            {"title": "Example", "bullets": ["Example"]}
                            for _ in range(3)
                        ],
                    }
                )
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(respond))
    HTTPXClientInstrumentor.instrument_client(client, tracer_provider=tracing.provider)
    settings = Settings(
        "unused",
        "unused",
        "unused",
        "http://identity.test",
        "worker",
        "synthetic",
        "http://gateway.test",
        str(tmp_path),
    )
    kafka = object.__new__(Kafka)
    kafka.producer, kafka.consumer = Producer(), Consumer()
    runtime = Runtime(Worker(str(tmp_path), Gateway(settings, client), kafka), kafka)
    runtime.run()
    client.close()
    finished = exporter.get_finished_spans()
    consumed = next(s for s in finished if s.kind == trace.SpanKind.CONSUMER)
    request_send = next(s for s in finished if s.name == "send skill.requests.slides")
    assert consumed.parent.span_id == request_send.context.span_id
    assert all(s.context.trace_id == consumed.context.trace_id for s in finished)
    assert len(calls) == 2
    for call in calls:
        assert call.headers["traceparent"].split("-")[1] == format(
            consumed.context.trace_id, "032x"
        )
    assert {t for t, _ in sent} == {"skill.results", "audit.events"}
    for topic, kwargs in sent:
        producer = next(s for s in finished if s.name == "send " + topic)
        assert producer.parent.span_id == consumed.context.span_id
        assert dict(kwargs["headers"])["traceparent"].decode().split("-")[1] == format(
            consumed.context.trace_id, "032x"
        )
        if topic == "audit.events":
            assert json.loads(kwargs["value"])["payload"]["trace_id"] == format(
                consumed.context.trace_id, "032x"
            )
