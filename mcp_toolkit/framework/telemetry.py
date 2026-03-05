"""OpenTelemetry instrumentation for MCP tool calls."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class SpanRecord:
    """Record of a completed telemetry span."""

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
    """Telemetry provider that wraps OpenTelemetry or falls back to in-memory recording.

    In production, initializes real OTel tracers. For testing and lightweight usage,
    records spans in memory.
    """

    def __init__(self, service_name: str = "mcp-server") -> None:
        self._service_name = service_name
        self._spans: list[SpanRecord] = []
        self._tracer: Any | None = None
        self._initialized = False

    def initialize(self, use_otel: bool = False) -> None:
        """Initialize telemetry. Uses in-memory recording unless use_otel=True."""
        if use_otel:
            try:
                from opentelemetry import trace
                from opentelemetry.sdk.resources import Resource
                from opentelemetry.sdk.trace import TracerProvider

                resource = Resource.create({"service.name": self._service_name})
                provider = TracerProvider(resource=resource)
                trace.set_tracer_provider(provider)
                self._tracer = trace.get_tracer(self._service_name)
            except ImportError:
                pass
        self._initialized = True

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def spans(self) -> list[SpanRecord]:
        return list(self._spans)

    def clear_spans(self) -> None:
        self._spans.clear()

    @asynccontextmanager
    async def span(
        self, name: str, attributes: dict[str, Any] | None = None
    ) -> AsyncIterator[SpanRecord]:
        """Create a telemetry span for a tool invocation."""
        record = SpanRecord(
            name=name,
            start_time=time.monotonic(),
            end_time=0,
            attributes=attributes or {},
        )
        try:
            yield record
            record.status = "ok"
        except Exception as exc:
            record.status = "error"
            record.error = str(exc)
            raise
        finally:
            record.end_time = time.monotonic()
            self._spans.append(record)

    def record_tool_call(
        self, tool_name: str, duration_ms: float, success: bool, **attrs: Any
    ) -> None:
        """Record a completed tool call as a span."""
        now = time.monotonic()
        self._spans.append(
            SpanRecord(
                name=f"tool.{tool_name}",
                start_time=now - (duration_ms / 1000),
                end_time=now,
                attributes=attrs,
                status="ok" if success else "error",
            )
        )
