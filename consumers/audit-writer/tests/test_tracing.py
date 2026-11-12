# SPDX-License-Identifier: AGPL-3.0-only
import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from opentelemetry import context, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, Status, StatusCode

from consumer import tracing
from consumer.app import create_app


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Any, Any]]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource({"service.name": "audit-writer"}))
    provider.add_span_processor(BatchSpanProcessor(tracing.FilteringExporter(exporter)))
    monkeypatch.setattr(tracing, "_provider", provider)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.invalid")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "audit-writer")
    yield provider, exporter
    provider.shutdown()


@pytest.mark.parametrize("endpoint", [None, "", "  "])
def test_disabled_registers_no_provider_or_exporter(
    monkeypatch: pytest.MonkeyPatch, endpoint: str | None
) -> None:
    monkeypatch.setattr(tracing, "_provider", None)
    if endpoint is None:
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    else:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("disabled tracing must not create a provider or exporter")

    monkeypatch.setattr(tracing, "TracerProvider", forbidden)
    monkeypatch.setattr(tracing, "OTLPSpanExporter", forbidden)
    original = trace.get_tracer_provider()
    app = create_app()
    assert app.state.tracing_provider is None and tracing._provider is None
    with tracing.span("disabled"):
        assert tracing.trace_id() is None
    assert trace.get_tracer_provider() is original


def test_configure_uses_batch_filter_and_five_second_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tracing, "_provider", None)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.invalid")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "audit-writer")
    exporter = InMemorySpanExporter()
    timeouts = []

    def factory(**kwargs: Any) -> Any:
        timeouts.append(kwargs["timeout"])
        return exporter

    monkeypatch.setattr(tracing, "OTLPSpanExporter", factory)
    provider = tracing.configure()
    assert provider is tracing.configure() and timeouts == [5]
    with tracing.span("configured") as current:
        current.set_attribute("url.full", "private-marker")
        current.set_attribute("ooh.status", "ok")
    provider.force_flush()
    assert exporter.get_finished_spans()[0].attributes == {"ooh.status": "ok"}
    assert provider.resource.attributes["service.name"] == "audit-writer"
    provider.shutdown()


def test_unhandled_route_error_is_filtered_including_status(
    spans: tuple[Any, Any],
) -> None:
    provider, exporter = spans
    app = create_app()

    @app.get("/test-failure")
    async def failure() -> None:
        raise RuntimeError("private-marker")

    client = TestClient(app, raise_server_exceptions=False)
    assert (
        client.get(
            "/test-failure?private=private-marker",
            headers={"User-Agent": "private-marker"},
        ).status_code
        == 500
    )
    provider.force_flush()
    exported = exporter.get_finished_spans()
    assert exported and any(s.status.status_code == StatusCode.ERROR for s in exported)
    for item in exported:
        assert not item.events
        assert set(item.attributes) <= tracing.ALLOWED
        assert "private-marker" not in item.to_json()
        assert item.status.description is None


def test_filter_retains_only_error_code_and_no_events(spans: tuple[Any, Any]) -> None:
    provider, exporter = spans
    with tracing.span("fixed") as current:
        current.set_attribute("ooh.error_code", "handler_failed")
        current.set_attribute("url.full", "private-marker")
        current.add_event("private-marker", {"exception.message": "private-marker"})
        current.set_status(Status(StatusCode.ERROR, "private-marker"))
    provider.force_flush()
    item = exporter.get_finished_spans()[0]
    assert item.status.description == "handler_failed"
    assert not item.events and "private-marker" not in item.to_json()


@pytest.mark.anyio
async def test_internal_http_parent_and_no_health_spans(spans: tuple[Any, Any]) -> None:
    provider, exporter = spans
    app = create_app()

    @app.get("/test-parent")
    async def parent() -> dict[str, str]:
        return {"trace_id": tracing.trace_id()}

    async def remote(request: httpx.Request) -> httpx.Response:
        token = context.attach(context.Context())
        try:
            return await httpx.ASGITransport(app=app).handle_async_request(request)
        finally:
            context.detach(token)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(remote), base_url="http://internal.invalid"
    ) as client:
        tracing.instrument_client(client)
        with tracing.span("caller") as root:
            response = await client.get("/test-parent")
            assert response.json()["trace_id"] == format(
                root.get_span_context().trace_id, "032x"
            )
    provider.force_flush()
    items = exporter.get_finished_spans()
    server = next(s for s in items if s.kind == SpanKind.SERVER)
    outgoing = next(s for s in items if s.kind == SpanKind.CLIENT)
    assert server.attributes["http.request.method"] == "GET"
    assert server.attributes["http.route"] == "/test-parent"
    assert server.attributes["http.response.status_code"] == 200
    assert server.parent.span_id == outgoing.context.span_id
    assert outgoing.parent.span_id == root.get_span_context().span_id
    # Excluded requests never create a server span even when their handler fails.
    TestClient(app, raise_server_exceptions=False).get("/health")
    provider.force_flush()
    assert len(exporter.get_finished_spans()) == len(items)


def test_w3c_headers_round_trip_and_malformed_values(spans: tuple[Any, Any]) -> None:
    incoming = [
        ("traceparent", ("00-" + "1" * 32 + "-" + "2" * 16 + "-01").encode()),
        ("tracestate", b"demo=1"),
    ]
    with tracing.span("continued", context=tracing.extract(incoming)):
        assert dict(tracing.headers())["tracestate"] == b"demo=1"
        assert tracing.trace_id() == "1" * 32
    with tracing.span("root") as root:
        headers = tracing.headers()
    with tracing.span("child", context=tracing.extract(headers)) as child:
        assert child.get_span_context().trace_id == root.get_span_context().trace_id
    for headers in [
        [("traceparent", b"\xff")],
        [("traceparent", None)],
        [("traceparent", b"invalid")],
    ]:
        with tracing.span("new-root", context=tracing.extract(headers)) as current:
            assert (
                current.get_span_context().trace_id != root.get_span_context().trace_id
            )


@pytest.mark.anyio
async def test_kafka_parent_send_headers_and_audit_payload(
    spans: tuple[Any, Any],
) -> None:
    from test_events import event

    from consumer.events import Bus, Processor, outgoing

    provider, exporter = spans
    sent = []

    class Producer:
        def produce(self, topic: str, **kwargs: Any) -> None:
            sent.append((topic, kwargs))

        def flush(self, timeout: int) -> int:
            return 0

    bus = object.__new__(Bus)
    bus.producer = Producer()
    value = event()
    value["payload"]["trace_id"] = "1" * 32

    async def handle(topic: str, incoming: dict[str, Any]) -> None:
        await bus.publish(
            "audit.events",
            outgoing(incoming, "fake-producer", "audit.event", value["payload"]),
        )

    with tracing.span("origin") as root:
        incoming_headers = tracing.headers()
    await Processor("fake-consumer", bus, handle).process(
        "audit.events", json.dumps(value).encode(), incoming_headers
    )
    provider.force_flush()
    items = exporter.get_finished_spans()
    consumed = next(s for s in items if s.kind == SpanKind.CONSUMER)
    produced = next(s for s in items if s.kind == SpanKind.PRODUCER)
    assert consumed.parent.span_id == root.get_span_context().span_id
    assert produced.parent.span_id == consumed.context.span_id
    assert (
        consumed.context.trace_id
        == produced.context.trace_id
        == root.get_span_context().trace_id
    )
    headers = dict(sent[0][1]["headers"])
    assert headers["traceparent"].decode().split("-")[1] == format(
        consumed.context.trace_id, "032x"
    )
    assert headers["traceparent"].decode().split("-")[2] == format(
        produced.context.span_id, "016x"
    )
    assert json.loads(sent[0][1]["value"])["payload"]["trace_id"] == format(
        consumed.context.trace_id, "032x"
    )
    assert sent[0][1]["key"] == value["correlation_id"]
    assert not any(s.events for s in items)


def test_schema_copies_are_byte_identical_and_audit_trace_is_accepted() -> None:
    from pathlib import Path

    from test_events import event

    from consumer.events import SCHEMA

    folder = Path(__file__).resolve().parents[1] / "consumer/schemas"
    root = Path(__file__).resolve().parents[3]
    for path in folder.rglob("*.json"):
        assert (
            path.read_bytes()
            == (root / "contracts/events" / path.relative_to(folder)).read_bytes()
        )
    value = event()
    value["payload"]["trace_id"] = "1" * 32
    SCHEMA.validate(value)
    from jsonschema import ValidationError

    value["payload"]["trace_id"] = "0" * 32
    with pytest.raises(ValidationError):
        SCHEMA.validate(value)


def test_audit_omits_trace_id_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from test_events import event

    from consumer.events import outgoing

    monkeypatch.setattr(tracing, "_provider", None)
    value = event()
    assert (
        "trace_id"
        not in outgoing(value, "fake", "audit.event", value["payload"])["payload"]
    )


@pytest.mark.anyio
async def test_runner_passes_real_message_headers_into_processing(
    spans: tuple[Any, Any],
) -> None:
    from test_events import Bus, event

    from consumer.events import Processor, Runner

    provider, exporter = spans
    value = event()
    with tracing.span("origin") as root:
        headers = tracing.headers()

    class Message:
        def headers(self) -> Any:
            return headers

        def error(self) -> None:
            return None

        def topic(self) -> str:
            return "audit.events"

        def value(self) -> bytes:
            return json.dumps(value).encode()

    class Consumer:
        def subscribe(self, topics: list[str]) -> None:
            pass

        def poll(self, timeout: int) -> Message:
            return Message()

        def commit(self, **kwargs: Any) -> None:
            pass

        def close(self) -> None:
            pass

    bus = Bus()
    bus.consumer = Consumer()

    async def handle(topic: str, incoming: dict[str, Any]) -> None:
        assert tracing.trace_id() == format(root.get_span_context().trace_id, "032x")
        runner.stopping = True

    exits = []
    runner = Runner(
        bus, Processor("fake", bus, handle), ["audit.events"], exit_process=exits.append
    )
    await runner.run()
    assert not exits
    provider.force_flush()
    item = next(s for s in exporter.get_finished_spans() if s.kind == SpanKind.CONSUMER)
    assert item.parent.span_id == root.get_span_context().span_id
