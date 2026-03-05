"""Unit tests for TelemetryProvider — span recording, tool call tracking."""

from __future__ import annotations

import pytest

from mcp_toolkit.framework.telemetry import SpanRecord, TelemetryProvider


class TestSpanRecord:
    def test_duration_ms(self):
        span = SpanRecord(name="test", start_time=0.0, end_time=0.1)
        assert span.duration_ms == pytest.approx(100.0, abs=0.1)

    def test_attributes(self):
        span = SpanRecord(name="test", start_time=0, end_time=0, attributes={"key": "val"})
        assert span.attributes["key"] == "val"

    def test_default_status(self):
        span = SpanRecord(name="test", start_time=0, end_time=0)
        assert span.status == "ok"

    def test_error_status(self):
        span = SpanRecord(name="test", start_time=0, end_time=0, status="error", error="boom")
        assert span.error == "boom"


class TestTelemetryProvider:
    def test_not_initialized_by_default(self):
        tp = TelemetryProvider("test")
        assert tp.is_initialized is False

    def test_initialize(self):
        tp = TelemetryProvider("test")
        tp.initialize()
        assert tp.is_initialized is True

    def test_empty_spans(self, telemetry):
        assert telemetry.spans == []

    @pytest.mark.asyncio
    async def test_span_context_manager(self, telemetry):
        async with telemetry.span("my_op", {"key": "val"}) as s:
            pass
        spans = telemetry.spans
        assert len(spans) == 1
        assert spans[0].name == "my_op"
        assert spans[0].status == "ok"
        assert spans[0].duration_ms >= 0

    @pytest.mark.asyncio
    async def test_span_records_error(self, telemetry):
        with pytest.raises(ValueError):
            async with telemetry.span("bad_op") as s:
                raise ValueError("test error")
        spans = telemetry.spans
        assert len(spans) == 1
        assert spans[0].status == "error"
        assert spans[0].error == "test error"

    def test_record_tool_call(self, telemetry):
        telemetry.record_tool_call("query_db", duration_ms=50.0, success=True, rows=10)
        spans = telemetry.spans
        assert len(spans) == 1
        assert spans[0].name == "tool.query_db"
        assert spans[0].status == "ok"
        assert spans[0].attributes["rows"] == 10

    def test_record_failed_tool_call(self, telemetry):
        telemetry.record_tool_call("bad_tool", duration_ms=100.0, success=False)
        spans = telemetry.spans
        assert spans[0].status == "error"

    def test_clear_spans(self, telemetry):
        telemetry.record_tool_call("t1", duration_ms=10, success=True)
        telemetry.record_tool_call("t2", duration_ms=20, success=True)
        assert len(telemetry.spans) == 2
        telemetry.clear_spans()
        assert len(telemetry.spans) == 0

    @pytest.mark.asyncio
    async def test_multiple_spans(self, telemetry):
        async with telemetry.span("op1"):
            pass
        async with telemetry.span("op2"):
            pass
        assert len(telemetry.spans) == 2
