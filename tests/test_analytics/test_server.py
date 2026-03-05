"""Tests for Analytics MCP server."""

import pytest

from mcp_toolkit.framework.testing import MCPTestClient
from mcp_toolkit.servers.analytics.chart_generator import ChartConfig, ChartGenerator
from mcp_toolkit.servers.analytics.server import MetricsStore, configure
from mcp_toolkit.servers.analytics.server import mcp as analytics_mcp


@pytest.fixture
def store():
    s = MetricsStore()
    for i in range(10):
        s.record("response_time", 100 + i * 10, timestamp=f"2026-02-{16 + i // 5}T{10 + i}:00:00")
    s.record("response_time", 900, timestamp="2026-02-17T12:00:00")  # anomaly
    s.record("error_rate", 0.02, timestamp="2026-02-16T10:00:00")
    s.record("error_rate", 0.03, timestamp="2026-02-16T11:00:00")
    return s


@pytest.fixture
def client(store):
    configure(store=store)
    return MCPTestClient(analytics_mcp)


class TestQueryMetrics:
    async def test_query_avg(self, client):
        result = await client.call_tool(
            "query_metrics", {"metric": "response_time", "aggregation": "avg"}
        )
        assert "response_time" in result
        assert "avg" in result

    async def test_query_sum(self, client):
        result = await client.call_tool(
            "query_metrics", {"metric": "response_time", "aggregation": "sum"}
        )
        assert "sum" in result

    async def test_query_raw(self, client):
        result = await client.call_tool(
            "query_metrics", {"metric": "response_time", "aggregation": "none"}
        )
        assert "data points" in result

    async def test_query_no_data(self, client):
        result = await client.call_tool("query_metrics", {"metric": "nonexistent"})
        assert "nonexistent" in result or "No data" in result or "0.00" in result


class TestDetectAnomalies:
    async def test_detect_finds_anomaly(self, client):
        result = await client.call_tool("detect_anomalies", {"metric": "response_time"})
        assert "anomal" in result.lower()
        assert "900" in result

    async def test_no_anomalies_in_clean_data(self, client):
        result = await client.call_tool("detect_anomalies", {"metric": "error_rate"})
        assert "No anomalies" in result


class TestGenerateChart:
    async def test_generate_chart(self, client):
        result = await client.call_tool(
            "generate_chart",
            {"metric": "response_time", "chart_type": "bar", "title": "Response Times"},
        )
        assert "Chart generated" in result or "data points" in result

    async def test_chart_no_data(self, client):
        result = await client.call_tool("generate_chart", {"metric": "nonexistent"})
        assert "No data" in result


class TestRecordMetric:
    async def test_record_new_metric(self, client):
        result = await client.call_tool("record_metric", {"metric": "cpu_usage", "value": 75.5})
        assert "Recorded" in result
        assert "cpu_usage" in result


class TestListMetrics:
    async def test_lists_metrics(self, client):
        result = await client.call_tool("list_available_metrics", {})
        assert "response_time" in result
        assert "error_rate" in result


class TestMetricsStore:
    def test_aggregate_avg(self, store):
        avg = store.aggregate("response_time", "avg")
        assert avg > 0

    def test_aggregate_count(self, store):
        count = store.aggregate("response_time", "count")
        assert count == 11

    def test_detect_anomalies(self, store):
        anomalies = store.detect_anomalies("response_time", z_threshold=2.0)
        assert len(anomalies) >= 1
        assert any(a.value == 900 for a in anomalies)

    def test_list_metrics(self, store):
        metrics = store.list_metrics()
        assert "response_time" in metrics
        assert "error_rate" in metrics

    def test_total_points(self, store):
        assert store.total_points == 13


class TestChartGenerator:
    def test_generate_text_fallback(self):
        gen = ChartGenerator()
        gen._matplotlib_available = False
        result = gen.generate(
            {"labels": ["Jan", "Feb"], "revenue": [100, 200]},
            ChartConfig(title="Revenue"),
        )
        assert result.is_success
        assert result.data_points == 2

    def test_generate_no_data(self):
        gen = ChartGenerator()
        result = gen.generate({"labels": []}, ChartConfig())
        assert not result.is_success
        assert "No data" in result.error

    def test_chart_config_defaults(self):
        config = ChartConfig()
        assert config.chart_type == "bar"
        assert config.width == 10


class TestToolListing:
    async def test_has_expected_tools(self, client):
        tools = await client.list_tools()
        names = {t["name"] for t in tools}
        assert "query_metrics" in names
        assert "detect_anomalies" in names
        assert "generate_chart" in names
        assert "list_available_metrics" in names
        assert "record_metric" in names
