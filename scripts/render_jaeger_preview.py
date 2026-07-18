"""Render a Jaeger-style trace preview from real TelemetryProvider spans.

Used when Docker/Render are unavailable — spans come from the same
seed_traces workflow code path, not fabricated metrics.
"""

from __future__ import annotations

import asyncio
import html
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples" / "observability"))

from seed_traces import WORKFLOWS, fire_workflow  # noqa: E402

from mcp_toolkit.framework.costing import CostTracker  # noqa: E402
from mcp_toolkit.framework.telemetry import TelemetryProvider  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT_HTML = ROOT / "assets" / "jaeger-trace-preview.html"
OUT_PNG = ROOT / "assets" / "jaeger-trace-demo.png"


def _render_html(spans: list, service: str) -> str:
    rows = []
    for span in spans:
        attrs = span.attributes
        cost = attrs.get("llm.cost_usd") or attrs.get("tool.cost_usd_partial", "")
        cache = attrs.get("workflow.cache_hit", attrs.get("tool.cache_hit", ""))
        duration_ms = round((span.end_time - span.start_time) * 1000, 2)
        rows.append(
            f"<tr>"
            f"<td>{html.escape(span.name)}</td>"
            f"<td>{duration_ms}</td>"
            f"<td>{html.escape(str(cache))}</td>"
            f"<td>{html.escape(str(cost))}</td>"
            f"<td><code>{html.escape(str(attrs))}</code></td>"
            f"</tr>"
        )

    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Jaeger — mcp-toolkit-demo</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; background: #1a1a2e; color: #e8e8e8; }}
    header {{ background: #16213e; padding: 12px 20px; border-bottom: 2px solid #0f3460; }}
    header h1 {{ margin: 0; font-size: 18px; color: #e94560; }}
    header p {{ margin: 4px 0 0; font-size: 13px; color: #a0a0b0; }}
    main {{ padding: 16px 20px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th {{ text-align: left; background: #0f3460; padding: 8px; }}
    td {{ border-top: 1px solid #2a2a4a; padding: 8px; vertical-align: top; }}
    code {{ font-size: 11px; color: #7fdbca; word-break: break-all; }}
    .badge {{ display: inline-block; background: #0f3460; border-radius: 4px; padding: 2px 8px; margin-right: 6px; font-size: 12px; }}
  </style>
</head>
<body>
  <header>
    <h1>Jaeger UI — Trace Preview</h1>
    <p>Service: <span class="badge">{html.escape(service)}</span>
       Spans: <span class="badge">{len(spans)}</span>
       Source: in-memory TelemetryProvider (same APIs as OTLP export)</p>
  </header>
  <main>
    <table>
      <thead>
        <tr><th>Operation</th><th>Duration (ms)</th><th>cache_hit</th><th>cost_usd</th><th>Attributes</th></tr>
      </thead>
      <tbody>
        {"".join(rows)}
      </tbody>
    </table>
  </main>
</body>
</html>"""
    return body


async def main() -> None:
    random.seed(42)
    telemetry = TelemetryProvider("mcp-toolkit-demo")
    telemetry.initialize(use_otel=False)
    cost = CostTracker()

    for spec in WORKFLOWS[:3]:
        await fire_workflow(telemetry, cost, spec)

    spans = telemetry.spans
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(_render_html(spans, "mcp-toolkit-demo"))
    print(f"Wrote {OUT_HTML} ({len(spans)} spans)")


if __name__ == "__main__":
    asyncio.run(main())
