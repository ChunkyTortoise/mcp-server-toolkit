"""Analytics MCP Server — Query metrics, generate charts, detect anomalies."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from mcp_toolkit.framework.base_server import EnhancedMCP
from mcp_toolkit.servers.analytics.chart_generator import ChartConfig, ChartGenerator

mcp = EnhancedMCP("analytics")

_chart_generator = ChartGenerator()


@dataclass
class MetricPoint:
    timestamp: str
    value: float
    metric: str
    tags: dict[str, str] = field(default_factory=dict)


class MetricsStore:
    """In-memory metrics store for demo/testing. Replace with TimescaleDB/InfluxDB in production."""

    def __init__(self) -> None:
        self._metrics: list[MetricPoint] = []

    def record(
        self, metric: str, value: float, timestamp: str = "", tags: dict | None = None
    ) -> None:
        self._metrics.append(
            MetricPoint(timestamp=timestamp, value=value, metric=metric, tags=tags or {})
        )

    def query(self, metric: str, limit: int = 100) -> list[MetricPoint]:
        return [m for m in self._metrics if m.metric == metric][:limit]

    def aggregate(self, metric: str, agg: str = "avg") -> float:
        points = [m.value for m in self._metrics if m.metric == metric]
        if not points:
            return 0.0
        if agg == "avg":
            return sum(points) / len(points)
        if agg == "sum":
            return sum(points)
        if agg == "min":
            return min(points)
        if agg == "max":
            return max(points)
        if agg == "count":
            return float(len(points))
        return 0.0

    def detect_anomalies(self, metric: str, z_threshold: float = 2.0) -> list[MetricPoint]:
        """Detect anomalies using z-score method."""
        points = [m for m in self._metrics if m.metric == metric]
        if len(points) < 3:
            return []
        values = [p.value for p in points]
        mean = sum(values) / len(values)
        std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
        if std == 0:
            return []
        return [p for p in points if abs((p.value - mean) / std) > z_threshold]

    def list_metrics(self) -> list[str]:
        return sorted(set(m.metric for m in self._metrics))

    @property
    def total_points(self) -> int:
        return len(self._metrics)


_store = MetricsStore()


def configure(store: MetricsStore | None = None) -> None:
    global _store
    if store:
        _store = store


def get_store() -> MetricsStore:
    return _store


@mcp.tool()
async def query_metrics(
    metric: str,
    aggregation: str = "avg",
    limit: int = 100,
) -> str:
    """Query metrics with optional aggregation.

    Args:
        metric: Metric name (e.g., "response_time", "error_rate").
        aggregation: Aggregation function — "avg", "sum", "min", "max", "count", or "none" for raw data.
        limit: Max data points for raw queries.
    """
    if aggregation == "none":
        points = _store.query(metric, limit=limit)
        if not points:
            return f"No data for metric '{metric}'."
        lines = [f"**{metric}** — {len(points)} data points:"]
        for p in points[:50]:
            lines.append(f"  {p.timestamp or 'N/A'}: {p.value}")
        return "\n".join(lines)

    value = _store.aggregate(metric, agg=aggregation)
    return f"**{metric}** ({aggregation}): {value:.2f}"


@mcp.tool()
async def detect_anomalies(
    metric: str,
    z_threshold: float = 2.0,
) -> str:
    """Detect anomalous data points using z-score analysis.

    Args:
        metric: Metric name to analyze.
        z_threshold: Z-score threshold for anomaly detection (default 2.0).
    """
    anomalies = _store.detect_anomalies(metric, z_threshold=z_threshold)
    if not anomalies:
        return f"No anomalies detected for '{metric}' (threshold: {z_threshold})."
    lines = [f"**{len(anomalies)} anomalies detected in '{metric}':**"]
    for a in anomalies:
        lines.append(f"  {a.timestamp or 'N/A'}: {a.value} (anomalous)")
    return "\n".join(lines)


@mcp.tool()
async def generate_chart(
    metric: str,
    chart_type: str = "bar",
    title: str = "",
) -> str:
    """Generate a chart for a metric.

    Args:
        metric: Metric name to visualize.
        chart_type: Chart type — "bar", "line", "pie", or "scatter".
        title: Chart title.
    """
    points = _store.query(metric, limit=100)
    if not points:
        return f"No data for metric '{metric}'."

    data = {
        "labels": [p.timestamp or f"t{i}" for i, p in enumerate(points)],
        metric: [p.value for p in points],
    }
    config = ChartConfig(chart_type=chart_type, title=title or metric, y_label=metric)
    result = _chart_generator.generate(data, config)

    if not result.is_success:
        return f"Chart error: {result.error}"

    return f"Chart generated: {result.chart_type}, {result.data_points} data points. Base64 image length: {len(result.image_base64)}"


@mcp.tool()
async def list_available_metrics() -> str:
    """List all available metrics in the store."""
    metrics = _store.list_metrics()
    if not metrics:
        return "No metrics recorded yet."
    lines = [f"**{len(metrics)} metrics available:**"]
    for m in metrics:
        count = _store.aggregate(m, agg="count")
        lines.append(f"  - {m} ({int(count)} data points)")
    return "\n".join(lines)


@mcp.tool()
async def record_metric(
    metric: str,
    value: float,
    timestamp: str = "",
) -> str:
    """Record a new metric data point.

    Args:
        metric: Metric name.
        value: Metric value.
        timestamp: Optional ISO 8601 timestamp.
    """
    _store.record(metric, value, timestamp=timestamp)
    return f"Recorded {metric}={value}"
