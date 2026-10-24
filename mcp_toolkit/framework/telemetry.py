"""OpenTelemetry instrumentation for MCP tool calls."""

from __future__ import annotations

import logging
import os
import sys
import time
from collections import deque
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from mcp_toolkit.framework.errors import Forbidden, RateLimited, Unauthorized

logger = logging.getLogger(__name__)

MAX_SPAN_RECORDS = 1000

# Attributes for the toolkit-decorated call in flight. Guards such as
# requires_scope add to it; the decorator records them as one span when the call ends.
_call_attrs: ContextVar[dict[str, Any] | None] = ContextVar("mcp_toolkit_call_attrs", default=None)


def annotate_call(**attrs: Any) -> None:
    """Add attributes to the span of the toolkit-decorated call in flight (no-op outside one)."""
    current = _call_attrs.get()
    if current is not None:
        current.update(attrs)


def classify_outcome(exc: BaseException | None) -> str:
    """Map the exception a tool raised (or None) to a ``tool.outcome`` value."""
    if exc is None:
        return "ok"
    if isinstance(exc, Unauthorized):
        return "unauthorized"
    if isinstance(exc, Forbidden):
        return "forbidden"
    if isinstance(exc, RateLimited):
        return "rate_limited"
    return "error"


@dataclass
class SpanRecord:
    """In-memory record of a completed telemetry span (used for testing)."""

    name: str
    start_time: float
    end_time: float
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    error: str | None = None

    @property
    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000


class TelemetryProvider:
    """OTel-first telemetry provider for MCP tool calls.

    When ``use_otel=True``, creates real OpenTelemetry spans exported via OTLP
    or a console fallback on stderr (stdout is the JSON-RPC channel of a stdio
    server). Always maintains a bounded in-memory ``SpanRecord`` deque (last
    1000) for unit-test assertions regardless of OTel mode.

    Environment variables (when use_otel=True):
        OTEL_EXPORTER_OTLP_ENDPOINT   OTLP HTTP endpoint (e.g. http://localhost:4318).
                                      Omit to use the console exporter instead.
        OTEL_EXPORTER_OTLP_HEADERS    Comma-separated key=value auth headers for
                                      managed OTLP backends (e.g. Grafana Cloud).
        OTEL_SERVICE_NAME             Overrides the service_name passed to __init__.
    """

    def __init__(self, service_name: str = "mcp-server") -> None:
        self._service_name = service_name
        self._spans: deque[SpanRecord] = deque(maxlen=MAX_SPAN_RECORDS)
        self._tracer: Any | None = None
        self._initialized = False

    def initialize(self, use_otel: bool = False, span_exporter: Any | None = None) -> None:
        """Initialize telemetry. Pass use_otel=True to enable real OTel tracing.

        ``span_exporter`` (for example an ``InMemorySpanExporter``) enables OTel with a
        ``SimpleSpanProcessor`` and a tracer provider local to this instance, without
        touching the process-global tracer provider, which can be set once per process.
        """
        if use_otel or span_exporter is not None:
            self._tracer = self._init_otel_tracer(span_exporter)
        self._initialized = True

    def _init_otel_tracer(self, span_exporter: Any | None = None) -> Any | None:
        """Set up OTel tracer provider with OTLP or console exporter."""
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.resources import SERVICE_NAME, Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import (
                BatchSpanProcessor,
                ConsoleSpanExporter,
                SimpleSpanProcessor,
            )
        except ImportError:
            logger.warning(
                "opentelemetry-sdk not installed; OTel disabled. "
                "Install with: pip install 'mcp-server-toolkit[telemetry]'"
            )
            return None

        service = os.environ.get("OTEL_SERVICE_NAME", self._service_name)
        resource = Resource.create({SERVICE_NAME: service})
        provider = TracerProvider(resource=resource)

        if span_exporter is not None:
            provider.add_span_processor(SimpleSpanProcessor(span_exporter))
            return provider.get_tracer(service)

        otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
        if otlp_endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

                headers_raw = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "")
                headers = (
                    {k: v for pair in headers_raw.split(",") if "=" in pair for k, v in [pair.split("=", 1)]}
                    if headers_raw
                    else {}
                )
                exporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces", headers=headers)
                logger.info("OTel OTLP exporter configured: %s", otlp_endpoint)
            except ImportError:
                logger.warning(
                    "opentelemetry-exporter-otlp-proto-http not installed; "
                    "falling back to console exporter. "
                    "Install with: pip install 'mcp-server-toolkit[telemetry]'"
                )
                exporter = ConsoleSpanExporter(out=sys.stderr)
        else:
            exporter = ConsoleSpanExporter(out=sys.stderr)

        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        tracer = trace.get_tracer(service)
        logger.info("OTel tracer initialized for service '%s'", service)
        return tracer

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def spans(self) -> list[SpanRecord]:
        """In-memory span records, useful for unit-test assertions."""
        return list(self._spans)

    def clear_spans(self) -> None:
        self._spans.clear()

    @asynccontextmanager
    async def span(
        self, name: str, attributes: dict[str, Any] | None = None
    ) -> AsyncIterator[SpanRecord]:
        """Create a telemetry span. Emits a real OTel span when a tracer is configured."""
        attrs = attributes or {}
        record = SpanRecord(
            name=name,
            start_time=time.monotonic(),
            end_time=0,
            attributes=dict(attrs),
        )

        otel_span: Any | None = None
        if self._tracer is not None:
            span = self._tracer.start_span(name)
            otel_span = span
            for k, v in attrs.items():
                span.set_attribute(str(k), _otel_safe(v))

        try:
            yield record
            record.status = "ok"
            if otel_span is not None:
                from opentelemetry.trace import StatusCode

                otel_span.set_status(StatusCode.OK)
        except Exception as exc:
            record.status = "error"
            record.error = str(exc)
            if otel_span is not None:
                from opentelemetry.trace import StatusCode

                otel_span.set_status(StatusCode.ERROR, str(exc))
                otel_span.record_exception(exc)
            raise
        finally:
            record.end_time = time.monotonic()
            self._spans.append(record)
            if otel_span is not None:
                otel_span.end()

    @asynccontextmanager
    async def tool_call(self, tool_name: str) -> AsyncIterator[dict[str, Any]]:
        """Record exactly one span for a toolkit-decorated call, whatever its outcome.

        Yields a dict the body can add attributes to (``cache_hit``, or ``mcp.subject``
        via :func:`annotate_call`). ``tool.outcome`` is classified from the exception
        the tool raised, before FastMCP wraps it in a generic ToolError.
        """
        attrs: dict[str, Any] = {}
        reset = _call_attrs.set(attrs)
        start = time.monotonic()
        error: BaseException | None = None
        try:
            yield attrs
        except BaseException as exc:
            error = exc
            raise
        finally:
            _call_attrs.reset(reset)
            outcome = classify_outcome(error)
            self.record_tool_call(
                tool_name,
                (time.monotonic() - start) * 1000,
                outcome == "ok",
                **{**attrs, "tool.outcome": outcome},
            )

    def record_tool_call(
        self, tool_name: str, duration_ms: float, success: bool, **attrs: Any
    ) -> None:
        """Record a completed tool call as both an in-memory SpanRecord and an OTel span."""
        now = time.monotonic()
        all_attrs: dict[str, Any] = {
            "tool.name": tool_name,
            "tool.duration_ms": round(duration_ms, 3),
            "tool.success": success,
            **attrs,
        }
        self._spans.append(
            SpanRecord(
                name=f"tool.{tool_name}",
                start_time=now - (duration_ms / 1000),
                end_time=now,
                attributes=all_attrs,
                status="ok" if success else "error",
            )
        )

        if self._tracer is not None:
            # Emit a real OTel span. Start time is approximate (reconstructed from duration).
            end_ns = time.time_ns()
            otel_span = self._tracer.start_span(
                f"tool.{tool_name}", start_time=end_ns - int(duration_ms * 1_000_000)
            )
            for k, v in all_attrs.items():
                otel_span.set_attribute(str(k), _otel_safe(v))
            from opentelemetry.trace import StatusCode

            otel_span.set_status(StatusCode.OK if success else StatusCode.ERROR)
            otel_span.end(end_time=end_ns)


def _otel_safe(value: Any) -> bool | int | float | str:
    """Coerce a value to an OTel-compatible attribute type."""
    if isinstance(value, (bool, int, float, str)):
        return value
    return str(value)
