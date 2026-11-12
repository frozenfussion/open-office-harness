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
            tracing.annotate_event(
                {
                    "correlation_id": "job-id",
                    "user_id": "test-user",
                    "payload": {"skill": "slides", "text": "PRIVATE_MARKER"},
                }
            )
            assert dict(headers)["traceparent"].decode().split("-")[1] == format(
                parent.get_span_context().trace_id, "032x"
            )
        assert dict(headers)["tracestate"] == b"test=demo"
        with tracing.kafka_span("skill.requests.slides", headers):
            tracing.annotate_event(
                {
                    "correlation_id": "job-id",
                    "user_id": "test-user",
                    "payload": {"skill": "slides", "text": "PRIVATE_MARKER"},
                },
                job=True,
            )
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
    for span in (published, consumed):
        assert span.attributes["ooh.correlation_id"] == "job-id"
        assert span.attributes["ooh.user_id"] == "test-user"
        assert span.attributes["ooh.skill"] == "slides"
        assert "PRIVATE_MARKER" not in str(dict(span.attributes))
    assert consumed.attributes["ooh.job_id"] == "job-id"
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
        if span.kind in {trace.SpanKind.SERVER, trace.SpanKind.CLIENT}:
            assert span.attributes["http.request.method"] == "GET"
            assert span.attributes["http.response.status_code"] in {200, 500}
        assert not span.events
        assert set(span.attributes) <= tracing.ALLOWED
        assert "PRIVATE_MARKER" not in str(
            (span.name, dict(span.attributes), span.status.description)
        )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize("invalid", [False, True])
def test_runtime_consumer_gateway_and_real_producer(
    spans: Any, tmp_path: Path, invalid: bool
) -> None:
    import json

    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from test_worker import request

    from slides_worker.app import Kafka, Runtime
    from slides_worker.config import Settings
    from slides_worker.worker import Gateway, Worker

    tracer, exporter = spans
    event = request()
    if invalid:
        event["user_id"] = "PRIVATE_REJECTED_TEXT"
        event["correlation_id"] = "PRIVATE_REJECTED_TEXT"
        event["payload"]["skill"] = "PRIVATE_REJECTED_TEXT"
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
    if invalid:
        assert not calls
        assert [t for t, _ in sent] == ["dlq.skill.requests.slides"]
        for span in finished:
            assert "ooh.user_id" not in span.attributes
            assert "ooh.correlation_id" not in span.attributes
            assert "ooh.skill" not in span.attributes
            assert "ooh.job_id" not in span.attributes
            assert "PRIVATE_REJECTED_TEXT" not in str(
                (
                    span.name,
                    dict(span.attributes),
                    span.status.description,
                    span.events,
                )
            )
        return
    request_send = next(s for s in finished if s.name == "send skill.requests.slides")
    assert consumed.attributes["ooh.correlation_id"] == event["correlation_id"]
    assert consumed.attributes["ooh.job_id"] == event["correlation_id"]
    assert consumed.attributes["ooh.user_id"] == event["user_id"]
    assert consumed.attributes["ooh.skill"] == "slides"
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
        assert producer.attributes["ooh.correlation_id"] == event["correlation_id"]
        assert producer.attributes["ooh.user_id"] == event["user_id"]
        if topic == "skill.results":
            assert producer.attributes["ooh.skill"] == "slides"
        assert producer.parent.span_id == consumed.context.span_id
        assert dict(kwargs["headers"])["traceparent"].decode().split("-")[1] == format(
            consumed.context.trace_id, "032x"
        )
        if topic == "audit.events":
            assert json.loads(kwargs["value"])["payload"]["trace_id"] == format(
                consumed.context.trace_id, "032x"
            )


@pytest.mark.parametrize(
    "sampler,recording", [("always_off", False), ("always_on", True)]
)
def test_configure_reads_sampler_and_defaults_service_name(
    monkeypatch: pytest.MonkeyPatch, sampler: str, recording: bool
) -> None:
    monkeypatch.setattr(tracing, "provider", None)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://unused.test")
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", sampler)
    monkeypatch.delenv("OTEL_slides-worker", raising=False)
    monkeypatch.delenv("OTEL_SEMCONV_STABILITY_OPT_IN", raising=False)
    exporter = InMemorySpanExporter()
    monkeypatch.setattr(tracing, "OTLPSpanExporter", lambda **kwargs: exporter)
    provider = tracing.configure()
    assert provider is not None
    assert tracing.os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] == "http"
    assert provider.resource.attributes["service.name"] == "slides-worker"
    try:
        with provider.get_tracer("test").start_as_current_span("request") as span:
            assert span.is_recording() is recording
    finally:
        provider.shutdown()


@pytest.mark.anyio
async def test_stream_has_one_server_span_without_chunk_spans(spans: Any) -> None:
    from collections.abc import AsyncIterator

    from fastapi.responses import StreamingResponse

    _, exporter = spans
    app = FastAPI()

    async def chunks() -> AsyncIterator[str]:
        for _ in range(50):
            yield "data: example\n\n"

    @app.get("/stream")
    async def stream() -> StreamingResponse:
        return StreamingResponse(chunks(), media_type="text/event-stream")

    async with httpx.AsyncClient() as internal:
        tracing.instrument(app, internal)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://app.test"
        ) as client:
            response = await client.get("/stream")
    assert response.text.count("data: example") == 50
    finished = exporter.get_finished_spans()
    assert len(finished) == 1
    assert finished[0].kind == trace.SpanKind.SERVER
    assert not any("http send" in s.name or "http receive" in s.name for s in finished)


@pytest.mark.parametrize("status", list(trace.StatusCode))
def test_status_description_only_for_errors(
    spans: Any, caplog: pytest.LogCaptureFixture, status: trace.StatusCode
) -> None:
    tracer, exporter = spans
    with tracer.start_as_current_span("status") as span:
        span.set_attribute("ooh.error_code", "handling_failed")
        span.set_status(trace.Status(status))
    exported = exporter.get_finished_spans()[0]
    assert exported.status.status_code == status
    assert exported.status.description == (
        "handling_failed" if status == trace.StatusCode.ERROR else None
    )
    assert exported.attributes["ooh.error_code"] == "handling_failed"
    assert set(exported.attributes) <= tracing.ALLOWED
    assert not caplog.records
