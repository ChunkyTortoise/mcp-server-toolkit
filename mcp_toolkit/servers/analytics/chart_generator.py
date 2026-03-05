"""Chart generation utilities for analytics visualizations."""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import Any


@dataclass
class ChartConfig:
    """Configuration for a chart."""

    chart_type: str = "bar"  # bar, line, pie, scatter
    title: str = ""
    x_label: str = ""
    y_label: str = ""
    width: int = 10
    height: int = 6


@dataclass
class ChartResult:
    """Result of chart generation."""

    image_base64: str = ""
    chart_type: str = ""
    data_points: int = 0
    error: str | None = None

    @property
    def is_success(self) -> bool:
        return self.error is None and bool(self.image_base64)


class ChartGenerator:
    """Generate charts from data series.

    Uses matplotlib if available, otherwise returns a text-based representation.
    """

    def __init__(self) -> None:
        self._matplotlib_available = self._check_matplotlib()

    @staticmethod
    def _check_matplotlib() -> bool:
        try:
            import matplotlib

            return True
        except ImportError:
            return False

    def generate(
        self,
        data: dict[str, list[Any]],
        config: ChartConfig | None = None,
    ) -> ChartResult:
        """Generate a chart from data.

        Args:
            data: Dict with "labels" and one or more data series.
                  E.g., {"labels": ["Jan", "Feb"], "revenue": [100, 200]}
            config: Chart configuration.
        """
        config = config or ChartConfig()
        labels = data.get("labels", [])
        data_keys = [k for k in data if k != "labels"]

        if not labels or not data_keys:
            return ChartResult(
                error="No data to chart. Need 'labels' and at least one data series."
            )

        if self._matplotlib_available:
            return self._generate_matplotlib(data, labels, data_keys, config)
        return self._generate_text(data, labels, data_keys, config)

    def _generate_matplotlib(
        self,
        data: dict[str, list[Any]],
        labels: list[str],
        data_keys: list[str],
        config: ChartConfig,
    ) -> ChartResult:
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(config.width, config.height))

            for key in data_keys:
                values = data[key]
                if config.chart_type == "bar":
                    ax.bar(labels, values, label=key, alpha=0.7)
                elif config.chart_type == "line":
                    ax.plot(labels, values, label=key, marker="o")
                elif config.chart_type == "scatter":
                    ax.scatter(labels, values, label=key)

            if config.chart_type == "pie" and data_keys:
                ax.pie(data[data_keys[0]], labels=labels, autopct="%1.1f%%")

            ax.set_title(config.title)
            if config.x_label:
                ax.set_xlabel(config.x_label)
            if config.y_label:
                ax.set_ylabel(config.y_label)
            if len(data_keys) > 1 and config.chart_type != "pie":
                ax.legend()

            buf = io.BytesIO()
            fig.savefig(buf, format="png", bbox_inches="tight", dpi=100)
            plt.close(fig)
            buf.seek(0)
            img_base64 = base64.b64encode(buf.read()).decode()

            total_points = sum(len(data[k]) for k in data_keys)
            return ChartResult(
                image_base64=img_base64,
                chart_type=config.chart_type,
                data_points=total_points,
            )
        except Exception as e:
            return ChartResult(error=f"Chart generation error: {e}")

    def _generate_text(
        self,
        data: dict[str, list[Any]],
        labels: list[str],
        data_keys: list[str],
        config: ChartConfig,
    ) -> ChartResult:
        """Generate a text-based representation when matplotlib is unavailable."""
        lines = [f"Chart: {config.title or 'Untitled'} ({config.chart_type})"]
        lines.append("-" * 40)

        for i, label in enumerate(labels):
            values = ", ".join(f"{k}={data[k][i]}" for k in data_keys if i < len(data[k]))
            lines.append(f"  {label}: {values}")

        text_repr = "\n".join(lines)
        img_b64 = base64.b64encode(text_repr.encode()).decode()
        total_points = sum(len(data[k]) for k in data_keys)
        return ChartResult(
            image_base64=img_b64,
            chart_type=config.chart_type,
            data_points=total_points,
        )
