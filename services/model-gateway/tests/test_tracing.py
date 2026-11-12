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

from gateway import tracing
from gateway.app import create_app


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Any, Any]]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource({"service.name": "model-gateway"}))
    provider.add_span_processor(BatchSpanProcessor(tracing.FilteringExporter(exporter)))
    monkeypatch.setattr(tracing, "_provider", provider)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.invalid")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "model-gateway")
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
    monkeypatch.setenv("OTEL_SERVICE_NAME", "model-gateway")
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
    assert provider.resource.attributes["service.name"] == "model-gateway"
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
@pytest.mark.parametrize(
    "kind", ["openai_chat_completions", "openai_responses", "anthropic_messages"]
)
async def test_provider_has_one_manual_span_and_audit_context(
    spans: tuple[Any, Any], entry: Any, call: Any, kind: str
) -> None:
    import respx
    from conftest import FakeDatabase, FakeRegistry
    from test_stage3 import PATHS, response

    from gateway.engine import Engine
    from gateway.events import Events

    provider, exporter = spans
    sent = []

    class Producer:
        def produce(self, topic: str, **kwargs: Any) -> None:
            sent.append(kwargs)

        def flush(self, timeout: int) -> int:
            return 0

    publisher = object.__new__(Events)
    publisher.producer = Producer()
    entry = entry.model_copy(update={"api_type": kind})
    call = call.model_copy(update={"stream": False})
    with respx.mock as mock:
        route = mock.post(entry.endpoint_url + PATHS[kind]).respond(
            200, json=response(kind)
        )
        async with (
            httpx.AsyncClient() as provider_client,
            httpx.AsyncClient() as internal_client,
        ):
            tracing.instrument_client(internal_client)
            engine = Engine(
                provider_client, FakeRegistry([entry]), FakeDatabase(), publisher
            )
            with tracing.span("request") as root:
                output = [event async for event in engine.events(call)]
            await engine.drain_background()
        assert "traceparent" not in route.calls[0].request.headers
    provider.force_flush()
    items = exporter.get_finished_spans()
    attempts = [s for s in items if s.name == "provider " + kind]
    assert len(attempts) == 1
    assert attempts[0].parent.span_id == root.get_span_context().span_id
    assert attempts[0].attributes["ooh.tokens"] == 11
    assert attempts[0].attributes["ooh.attempt"] == 1
    assert not any(s.kind == SpanKind.CLIENT for s in items)
    assert output[-1]["type"] == "completed"
    audit = json.loads(sent[0]["value"])
    assert audit["payload"]["trace_id"] == format(
        root.get_span_context().trace_id, "032x"
    )
    produced = next(s for s in items if s.kind == SpanKind.PRODUCER)
    assert produced.parent.span_id == root.get_span_context().span_id
    assert dict(sent[0]["headers"])["traceparent"].decode().split("-")[2] == format(
        produced.context.span_id, "016x"
    )
    for item in items:
        assert set(item.attributes) <= tracing.ALLOWED and not item.events
        assert entry.endpoint_url not in item.to_json()


def test_audit_omits_invalid_trace_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import uuid4

    from gateway.events import envelope

    monkeypatch.setattr(tracing, "_provider", None)
    assert "trace_id" not in envelope(uuid4(), "fake", {})["payload"]


def test_gateway_lifespan_keeps_provider_client_uninstrumented(
    spans: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_http_identity_registry import CONFIG

    clients = []
    original = tracing.HTTPXClientInstrumentor.instrument_client

    def instrument(client: Any, **kwargs: Any) -> None:
        clients.append(client)
        original(client, **kwargs)

    monkeypatch.setattr(
        tracing.HTTPXClientInstrumentor, "instrument_client", instrument
    )
    app = create_app(CONFIG)
    with TestClient(app):
        assert app.state.engine.client not in clients
        assert app.state.identity.client in clients
        assert len(clients) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["openai_chat_completions", "jev_systemone"])
async def test_classify_span_contains_provider_attempts_and_audit_trace(
    spans: tuple[Any, Any], entry: Any, kind: str
) -> None:
    import respx
    from conftest import FakeDatabase, FakeRegistry
    from test_stage3 import PATHS, response

    from gateway.engine import Engine
    from gateway.models import Classify

    provider, exporter = spans
    entry = entry.model_copy(
        update={"api_type": kind, "purpose": "classification", "tier": None}
    )
    body = Classify(
        text="private-marker", questions={"risk": "private-marker"}, user_id="fake-user"
    )
    result = (
        {
            "answers": {"risk": {"noul": 0.25}},
            "usage": {"input_tokens": 3, "output_tokens": 2},
        }
        if kind == "jev_systemone"
        else response(kind, text='{"risk":0.25}')
    )
    with respx.mock as mock:
        mock.post(entry.endpoint_url + PATHS[kind]).respond(200, json=result)
        async with httpx.AsyncClient() as client:
            engine = Engine(client, FakeRegistry([entry]), FakeDatabase())
            with tracing.span("request") as root:
                answer = await engine.classify(body)
            await engine.drain_background()
    assert answer["scores"] == {"risk": 0.25}
    provider.force_flush()
    items = exporter.get_finished_spans()
    classify = next(s for s in items if s.name == "classify")
    attempt = next(s for s in items if s.name == "provider " + kind)
    assert classify.parent.span_id == root.get_span_context().span_id
    assert attempt.parent.span_id == classify.context.span_id
    assert attempt.attributes["ooh.status"] == "ok"
    assert not any(s.kind == SpanKind.CLIENT for s in items)
    assert all("private-marker" not in s.to_json() for s in items)


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["openai_chat_completions", "jev_systemone"])
async def test_failed_provider_attempt_has_error_code_without_diagnostics(
    spans: tuple[Any, Any], entry: Any, call: Any, kind: str
) -> None:
    import respx
    from conftest import FakeDatabase, FakeRegistry
    from test_stage3 import PATHS

    from gateway.engine import Engine
    from gateway.models import Classify, GatewayError

    provider, exporter = spans
    call = call.model_copy(update={"stream": False})
    if kind == "jev_systemone":
        entry = entry.model_copy(
            update={"api_type": kind, "purpose": "classification", "tier": None}
        )
    with respx.mock as mock:
        mock.post(entry.endpoint_url + PATHS[kind]).respond(500, text="private-marker")
        async with httpx.AsyncClient() as client:
            engine = Engine(client, FakeRegistry([entry]), FakeDatabase())
            with pytest.raises(GatewayError):
                if kind == "jev_systemone":
                    await engine.classify(
                        Classify(
                            text="private-marker",
                            questions={"risk": "private-marker"},
                            user_id="fake-user",
                        )
                    )
                else:
                    _ = [event async for event in engine.events(call)]
            await engine.drain_background()
    provider.force_flush()
    item = next(
        s for s in exporter.get_finished_spans() if s.name.startswith("provider ")
    )
    assert item.attributes["ooh.status"] == "failed"
    assert item.attributes["ooh.error_code"] == "provider_failed"
    assert item.status.status_code == StatusCode.ERROR
    assert item.status.description == "provider_failed"
    assert "private-marker" not in item.to_json() and not item.events


@pytest.mark.parametrize("service_name", [None, ""])
def test_missing_service_name_uses_deployment_name(
    monkeypatch: pytest.MonkeyPatch, service_name: str | None
) -> None:
    monkeypatch.setattr(tracing, "_provider", None)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.invalid")
    if service_name is None:
        monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    else:
        monkeypatch.setenv("OTEL_SERVICE_NAME", service_name)
    exporter = InMemorySpanExporter()
    monkeypatch.setattr(tracing, "OTLPSpanExporter", lambda **kwargs: exporter)
    app = create_app()
    provider = app.state.tracing_provider
    try:
        assert provider is not None
        assert provider.resource.attributes["service.name"] == "model-gateway"

        @app.get("/test-missing-service-name")
        async def ready() -> dict[str, str]:
            return {"status": "ok"}

        assert TestClient(app).get("/test-missing-service-name").json() == {
            "status": "ok"
        }
        provider.force_flush()
        assert exporter.get_finished_spans()
    finally:
        if provider is not None:
            provider.shutdown()
