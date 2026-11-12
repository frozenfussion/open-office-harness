# SPDX-License-Identifier: AGPL-3.0-only
import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import httpx
from fastapi import FastAPI
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
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

ALLOWED = frozenset(
    {
        "ooh.user_id",
        "ooh.conversation_id",
        "ooh.job_id",
        "ooh.correlation_id",
        "ooh.model_entry_id",
        "ooh.tier",
        "ooh.purpose",
        "ooh.skill",
        "ooh.status",
        "ooh.error_code",
        "ooh.attempt",
        "ooh.tokens",
        "ooh.connection_type",
        "http.request.method",
        "http.route",
        "http.response.status_code",
        "server.port",
        "messaging.destination.name",
        "messaging.operation.type",
    }
)
_provider: TracerProvider | None = None
_context = TraceContextTextMapPropagator()


class FilteringExporter(SpanExporter):
    def __init__(self, exporter: SpanExporter) -> None:
        self.exporter = exporter

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        clean = []
        for span in spans:
            attributes = {
                k: v for k, v in (span.attributes or {}).items() if k in ALLOWED
            }
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
                    status=Status(
                        span.status.status_code,
                        attributes.get("ooh.error_code")
                        if span.status.status_code == StatusCode.ERROR
                        else None,
                    ),
                    start_time=span.start_time,
                    end_time=span.end_time,
                    instrumentation_scope=span.instrumentation_scope,
                )
            )
        return self.exporter.export(clean)

    def shutdown(self) -> None:
        self.exporter.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.exporter.force_flush(timeout_millis)


def configure() -> TracerProvider | None:
    global _provider
    os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "http")
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip():
        return None
    if _provider is None:
        _provider = TracerProvider(
            resource=Resource(
                {"service.name": os.getenv("OTEL_SERVICE_NAME") or "safety-watcher"}
            )
        )
        _provider.add_span_processor(
            BatchSpanProcessor(
                FilteringExporter(OTLPSpanExporter(timeout=5)),
                export_timeout_millis=5000,
            )
        )
    return _provider


def instrument_app(app: FastAPI) -> None:
    provider = configure()
    app.state.tracing_provider = provider
    if provider is not None:
        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=provider,
            excluded_urls="health",
            exclude_spans=["receive", "send"],
        )


def instrument_client(client: httpx.AsyncClient) -> None:
    if _provider is not None:
        HTTPXClientInstrumentor.instrument_client(client, tracer_provider=_provider)


def tracer() -> trace.Tracer:
    return (
        _provider.get_tracer(__name__) if _provider is not None else trace.NoOpTracer()
    )


def trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None


def headers() -> list[tuple[str, bytes]]:
    carrier: dict[str, str] = {}
    _context.inject(carrier)
    return [(key, value.encode("utf-8")) for key, value in carrier.items()]


def extract(headers: list[tuple[str, bytes | str | None]] | None) -> Any:
    carrier = {}
    for key, value in headers or []:
        if key in {"traceparent", "tracestate"} and isinstance(value, (str, bytes)):
            try:
                carrier[key] = (
                    value.decode("utf-8") if isinstance(value, bytes) else value
                )
            except UnicodeDecodeError:
                continue
    return _context.extract(carrier)


@contextmanager
def span(
    name: str,
    *,
    kind: SpanKind = SpanKind.INTERNAL,
    context: Any = None,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Span]:
    with tracer().start_as_current_span(
        name,
        kind=kind,
        context=context,
        attributes=attributes,
        record_exception=False,
        set_status_on_exception=False,
    ) as current:
        try:
            yield current
        except BaseException:
            current.set_status(Status(StatusCode.ERROR))
            raise
