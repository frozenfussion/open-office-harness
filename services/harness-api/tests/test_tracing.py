# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from harness_api import tracing
from harness_api.events import Kafka, envelope


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
    assert "trace_id" not in envelope("audit.event", "id", "user", {})["payload"]
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    assert tracing.configure() is None


def test_schema_copies() -> None:
    root = Path(__file__).resolve().parents[3]
    package = Path(__file__).parents[1] / "harness_api/event_schemas"
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
            audit = envelope("audit.event", "id", "user", {})
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

    tracing.instrument(app, internal, public=True)
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
        second = await client.get(
            "/sample/PRIVATE_MARKER",
            headers={"traceparent": incoming, "X-Forwarded-For": "192.0.2.1"},
        )
        assert second.json()["trace_id"] != "1" * 32
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


@pytest.mark.anyio
async def test_real_publish_injects_before_thread_handoff(spans: Any) -> None:
    tracer, exporter = spans
    sent = []

    class Producer:
        def produce(self, topic: str, **kwargs: Any) -> None:
            sent.append(kwargs)
            kwargs["on_delivery"](None, None)

    kafka = object.__new__(Kafka)
    kafka.producer = Producer()
    kafka.send_pool = ThreadPoolExecutor(max_workers=1)
    kafka.send_slots = asyncio.BoundedSemaphore(1)
    try:
        with tracer.start_as_current_span("request") as parent:
            await kafka.publish(
                "audit.events",
                {
                    "correlation_id": "test",
                    "user_id": "test-user",
                    "payload": {"skill": "slides"},
                },
            )
        header = dict(sent[0]["headers"])["traceparent"].decode()
        assert header.split("-")[1] == format(
            parent.get_span_context().trace_id, "032x"
        )
        producer = next(
            s
            for s in exporter.get_finished_spans()
            if s.kind == trace.SpanKind.PRODUCER
        )
        assert producer.attributes["ooh.correlation_id"] == "test"
        assert producer.attributes["ooh.user_id"] == "test-user"
        assert producer.attributes["ooh.skill"] == "slides"
        assert producer.parent.span_id == parent.get_span_context().span_id
    finally:
        await kafka.close()


@pytest.mark.anyio
@pytest.mark.parametrize("topic", ["skill.results", "approvals.decided"])
async def test_consumer_real_path_extracts_headers(spans: Any, topic: str) -> None:
    from test_review_fixes import Consumer, result

    from harness_api.events import validator

    tracer, exporter = spans
    with tracer.start_as_current_span("upstream"):
        with tracing.kafka_span(topic) as headers:
            pass
    message = result()
    if topic == "approvals.decided":
        import json
        from uuid import uuid4

        message.content = json.dumps(
            envelope(
                "approval.decided",
                str(uuid4()),
                "test-user",
                {"approved": True, "decided_by": "test-admin", "note": ""},
            )
        )
    message.topic = lambda: topic
    message.headers = lambda: headers
    stop = asyncio.Event()
    kafka = object.__new__(Kafka)
    kafka.consumer = Consumer([message], stop)
    kafka.schema = validator()
    seen = []

    async def handle(topic: str, event: dict[str, Any]) -> None:
        seen.append(trace.get_current_span().get_span_context())

    await kafka.run(handle, stop)
    producer = next(
        s for s in exporter.get_finished_spans() if s.kind == trace.SpanKind.PRODUCER
    )
    consumer = next(
        s for s in exporter.get_finished_spans() if s.kind == trace.SpanKind.CONSUMER
    )
    import json

    original = json.loads(message.content)
    assert consumer.attributes["ooh.correlation_id"] == original["correlation_id"]
    assert consumer.attributes["ooh.user_id"] == "test-user"
    if topic == "skill.results":
        assert consumer.attributes["ooh.skill"] == "slides"
    assert consumer.parent.span_id == producer.context.span_id
    assert seen[0].trace_id == producer.context.trace_id


@pytest.mark.anyio
async def test_chat_routing_and_title_share_request_trace(h: Any, spans: Any) -> None:
    from dataclasses import replace

    _, exporter = spans
    h.app.state.upstream.settings = replace(
        h.app.state.upstream.settings, route_tier_question="Example rule"
    )
    h.router.post("http://gateway.test/v1/classify").respond(
        json={"scores": {"needs_tier2": 0, "wants_slides": 0}}
    )
    h.title_gateway.respond(json={"content": "Example title"})
    h.gateway.respond(
        text=h.sse([{"type": "delta", "text": "Example"}] * 50 + [h.completed()]),
        headers={"Content-Type": "text/event-stream"},
    )
    tracing.instrument(h.app, h.http, public=True)
    identifier = await h.conversation()
    exporter.clear()
    response = await h.send(identifier, tier="auto")
    assert response.status_code == 200
    await asyncio.gather(*list(h.app.state.chat_tasks))
    finished = exporter.get_finished_spans()
    server = next(s for s in finished if s.kind == trace.SpanKind.SERVER)
    assert len([s for s in finished if s.kind == trace.SpanKind.SERVER]) == 1
    assert not any("http send" in s.name or "http receive" in s.name for s in finished)
    assert server.attributes["ooh.conversation_id"] == identifier
    assert server.attributes["ooh.tier"] == 1
    clients = [s for s in finished if s.kind == trace.SpanKind.CLIENT]
    assert len(clients) >= 4
    assert all(s.context.trace_id == server.context.trace_id for s in clients)
    calls = [call.request for call in h.router.calls]
    assert any(r.url.path == "/v1/classify" for r in calls)
    assert h.title_gateway.called
    for request in calls:
        if request.url.path in {"/v1/call", "/v1/classify"}:
            assert request.headers["traceparent"].split("-")[1] == format(
                server.context.trace_id, "032x"
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
    monkeypatch.delenv("OTEL_harness-api", raising=False)
    monkeypatch.delenv("OTEL_SEMCONV_STABILITY_OPT_IN", raising=False)
    exporter = InMemorySpanExporter()
    monkeypatch.setattr(tracing, "OTLPSpanExporter", lambda **kwargs: exporter)
    provider = tracing.configure()
    assert provider is not None
    assert tracing.os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] == "http"
    assert provider.resource.attributes["service.name"] == "harness-api"
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


@pytest.mark.anyio
@pytest.mark.parametrize("topic", ["skill.results", "approvals.decided"])
async def test_invalid_message_ids_never_export(spans: Any, topic: str) -> None:
    import json

    from test_review_fixes import Consumer, Message, result

    from harness_api.events import validator

    _, exporter = spans
    event = json.loads(result().content)
    event["user_id"] = "PRIVATE_REJECTED_TEXT"
    event["correlation_id"] = "PRIVATE_REJECTED_TEXT"
    event["payload"]["skill"] = "PRIVATE_REJECTED_TEXT"
    message = Message(json.dumps(event))
    message.topic = lambda: topic
    sent = []

    class Producer:
        def produce(self, topic: str, **kwargs: Any) -> None:
            sent.append((topic, kwargs))
            kwargs["on_delivery"](None, None)

    stop = asyncio.Event()
    kafka = object.__new__(Kafka)
    kafka.consumer = Consumer([message], stop)
    kafka.schema = validator()
    kafka.producer = Producer()
    kafka.send_pool = ThreadPoolExecutor(max_workers=1)
    kafka.send_slots = asyncio.BoundedSemaphore(1)

    async def handle(topic: str, event: dict[str, Any]) -> None:
        pytest.fail("Invalid message reached the handler")

    try:
        await kafka.run(handle, stop)
    finally:
        await kafka.close()
    assert [t for t, _ in sent] == ["dlq." + topic]
    finished = exporter.get_finished_spans()
    assert {s.kind for s in finished} == {
        trace.SpanKind.CONSUMER,
        trace.SpanKind.PRODUCER,
    }
    for span in finished:
        assert "ooh.user_id" not in span.attributes
        assert "ooh.correlation_id" not in span.attributes
        assert "ooh.skill" not in span.attributes
        assert "PRIVATE_REJECTED_TEXT" not in str(
            (
                span.name,
                dict(span.attributes),
                span.status.description,
                span.events,
            )
        )
