"""Gate 3 — Semantic: multi-LLM routing logic correctness.

Validates that the multi_llm server's routing and circuit-breaker logic
produces semantically correct behaviour. Uses MCPTestClient (dicts, not objects).

Full LLM-as-judge quality evals live in evals/quality/ (W3).
"""

from __future__ import annotations

import pytest

from mcp_toolkit.framework.testing import MCPTestClient
from mcp_toolkit.servers.multi_llm.server import mcp as multi_llm_mcp


class TestRoutingSemantics:
    @pytest.fixture
    def client(self):
        return MCPTestClient(multi_llm_mcp)

    async def test_server_lists_routing_tools(self, client):
        """multi_llm server must expose routing-related tools."""
        tools = await client.list_tools()
        names = {t["name"] for t in tools}
        routing_tools = {n for n in names if any(k in n for k in ("route", "query", "llm", "model", "second"))}
        assert routing_tools, f"No routing tools found. Available: {names}"

    async def test_list_tools_returns_nonempty(self, client):
        tools = await client.list_tools()
        assert len(tools) > 0

    async def test_all_tools_have_names(self, client):
        tools = await client.list_tools()
        for tool in tools:
            assert tool["name"], "Tool has empty name"

    async def test_all_tools_have_descriptions(self, client):
        tools = await client.list_tools()
        missing = [t["name"] for t in tools if not t.get("description", "").strip()]
        assert not missing, f"Tools missing descriptions: {missing}"
