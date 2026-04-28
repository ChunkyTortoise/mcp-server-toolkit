"""Demo: MCP tool calls with real OTel spans visible in Jaeger.

Usage:
    docker compose up -d          # start Jaeger
    pip install 'mcp-server-toolkit[telemetry]'
    python examples/observability/demo.py
    open http://localhost:16686   # view traces
"""

import asyncio
import os

os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4318"
os.environ["OTEL_SERVICE_NAME"] = "mcp-toolkit-demo"

from mcp_toolkit import EnhancedMCP  # noqa: E402
from mcp_toolkit.framework.telemetry import TelemetryProvider  # noqa: E402


async def main() -> None:
    telemetry = TelemetryProvider("mcp-toolkit-demo")
    telemetry.initialize(use_otel=True)

    # Simulate a few tool calls
    for i in range(3):
        async with telemetry.span(
            "tool.example_query",
            {"tool.name": "example_query", "query.index": i},
        ):
            await asyncio.sleep(0.01 * (i + 1))  # simulate work

    telemetry.record_tool_call("cached_lookup", duration_ms=0.12, success=True, cache_hit=True)
    telemetry.record_tool_call("slow_fetch", duration_ms=142.7, success=True, cache_hit=False)

    print(f"Emitted {len(telemetry.spans)} spans — open http://localhost:16686 to view.")
    # Give BatchSpanProcessor time to flush before exit
    await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
