"""Run actual MCP tool dispatch and inspect cache telemetry without API keys.

Run from a supported source install: python examples/verified_cache.py
"""

import asyncio
import json

from mcp_toolkit import EnhancedMCP
from mcp_toolkit.framework.testing import MCPTestClient


async def run_demo() -> dict:
    server = EnhancedMCP("verified-cache")
    executions = 0

    @server.cached_tool(ttl=60)
    async def greet(name: str) -> str:
        nonlocal executions
        executions += 1
        return f"Hello, {name}!"

    client = MCPTestClient(server)
    results = [await client.call_tool("greet", {"name": "World"}) for _ in range(2)]
    return {
        "mode": "local MCP dispatch; in-memory telemetry; no external exporter",
        "results": results,
        "tool_executions": executions,
        "spans": [
            {"name": span.name, "status": span.status, "attributes": span.attributes}
            for span in server.telemetry.spans
        ],
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run_demo()), indent=2))
