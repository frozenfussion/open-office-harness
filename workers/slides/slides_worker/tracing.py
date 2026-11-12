# SPDX-License-Identifier: AGPL-3.0-only
import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased
from opentelemetry.trace import SpanKind, Status
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

ALLOWED = frozenset(
    "ooh.user_id ooh.conversation_id ooh.job_id ooh.correlation_id "
    "ooh.model_entry_id ooh.tier ooh.purpose ooh.skill ooh.status "
    "ooh.error_code ooh.attempt ooh.tokens ooh.connection_type "
    "http.request.method http.route http.response.status_code server.port "
    "messaging.destination.name messaging.operation.type".split()
)
provider: TracerProvider | None = None
propagator = TraceContextTextMapPropagator()


class FilteringExporter(SpanExporter):
    def __init__(self, delegate: SpanExporter) -> None:
        self.delegate = delegate

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        clean = []
        for span in spans:
            attributes = {k: v for k, v in span.attributes.items() if k in ALLOWED}
            clean.append(
                ReadableSpan(
                    name=span.name,
                    context=span.context,
                    parent=span.parent,
                    resource=span.resource,
                    attributes=attributes,
                    events=(),
                    links=(),
                    kind=span.kind,
                    start_time=span.start_time,
                    end_time=span.end_time,
                    status=Status(
                        span.status.status_code, attributes.get("ooh.error_code")
                    ),
                    instrumentation_scope=span.instrumentation_scope,
                )
            )
        return self.delegate.export(clean)

    def shutdown(self) -> None:
        self.delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.delegate.force_flush(timeout_millis)


def configure() -> TracerProvider | None:
    global provider
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return None
    if provider is None:
        provider = TracerProvider(
            resource=Resource.create({"service.name": os.environ["OTEL_SERVICE_NAME"]}),
            sampler=ParentBased(ALWAYS_ON),
        )
        provider.add_span_processor(
            BatchSpanProcessor(
                FilteringExporter(
                    OTLPSpanExporter(
                        endpoint=endpoint.rstrip("/") + "/v1/traces", timeout=5
                    )
                )
            )
        )
    return provider


def instrument(app: Any, client: Any) -> None:
    configured = configure()
    if configured is None:
        return
    HTTPXClientInstrumentor.instrument_client(client, tracer_provider=configured)
    FastAPIInstrumentor.instrument_app(
        app, tracer_provider=configured, excluded_urls="health"
    )


def audit_context() -> dict[str, str]:
    context = trace.get_current_span().get_span_context()
    return {"trace_id": format(context.trace_id, "032x")} if context.is_valid else {}


@contextmanager
def kafka_span(topic: str, headers: Any = None) -> Iterator[list[tuple[str, bytes]]]:
    consume = headers is not None
    carrier = {k: v.decode("utf-8", errors="replace") for k, v in (headers or []) if v}
    tracer = (provider or trace.get_tracer_provider()).get_tracer(__name__)
    with tracer.start_as_current_span(
        ("process " if consume else "send ") + topic,
        context=propagator.extract(carrier) if consume else None,
        kind=SpanKind.CONSUMER if consume else SpanKind.PRODUCER,
        attributes={
            "messaging.destination.name": topic,
            "messaging.operation.type": "process" if consume else "send",
        },
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        outgoing: dict[str, str] = {}
        propagator.inject(outgoing)
        try:
            yield [(k, v.encode("utf-8")) for k, v in outgoing.items()]
        except Exception:
            span.set_attribute("ooh.error_code", "handling_failed")
            span.set_status(Status(trace.StatusCode.ERROR))
            raise
