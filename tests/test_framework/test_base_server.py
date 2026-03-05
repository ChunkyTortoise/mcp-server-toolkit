"""Tests for EnhancedMCP base server."""

import pytest

from mcp_toolkit.framework.base_server import EnhancedMCP
from mcp_toolkit.framework.testing import MCPTestClient


class TestEnhancedMCPInit:
    def test_creates_with_name(self):
        server = EnhancedMCP("test-server")
        assert server.name == "test-server"

    def test_has_cache(self):
        server = EnhancedMCP("test")
        assert server.cache is not None
        assert server.cache.is_initialized

    def test_has_rate_limiter(self):
        server = EnhancedMCP("test")
        assert server.rate_limiter is not None

    def test_has_telemetry(self):
        server = EnhancedMCP("test")
        assert server.telemetry is not None
        assert server.telemetry.is_initialized


class TestCachedTool:
    @pytest.fixture
    def server_with_cached_tool(self):
        server = EnhancedMCP("cache-test")
        call_count = {"value": 0}

        @server.cached_tool(ttl=300)
        async def greet(name: str) -> str:
            call_count["value"] += 1
            return f"Hello, {name}!"

        return server, call_count

    async def test_cached_tool_returns_result(self, server_with_cached_tool):
        server, _ = server_with_cached_tool
        client = MCPTestClient(server)
        result = await client.call_tool("greet", {"name": "World"})
        assert result == "Hello, World!"

    async def test_cached_tool_caches_second_call(self, server_with_cached_tool):
        server, call_count = server_with_cached_tool
        client = MCPTestClient(server)
        await client.call_tool("greet", {"name": "World"})
        await client.call_tool("greet", {"name": "World"})
        assert call_count["value"] == 1

    async def test_cached_tool_different_args_not_cached(self, server_with_cached_tool):
        server, call_count = server_with_cached_tool
        client = MCPTestClient(server)
        await client.call_tool("greet", {"name": "Alice"})
        await client.call_tool("greet", {"name": "Bob"})
        assert call_count["value"] == 2

    async def test_cached_tool_records_telemetry(self, server_with_cached_tool):
        server, _ = server_with_cached_tool
        client = MCPTestClient(server)
        await client.call_tool("greet", {"name": "Test"})
        assert len(server.telemetry.spans) >= 1


class TestRateLimitedTool:
    @pytest.fixture
    def server_with_rate_limited_tool(self):
        server = EnhancedMCP("rate-test")

        @server.rate_limited_tool(max_calls=3, window_seconds=60)
        async def ping() -> str:
            return "pong"

        return server

    async def test_rate_limited_tool_allows_under_limit(self, server_with_rate_limited_tool):
        server = server_with_rate_limited_tool
        client = MCPTestClient(server)
        result = await client.call_tool("ping", {})
        assert result == "pong"

    async def test_rate_limited_tool_blocks_over_limit(self, server_with_rate_limited_tool):
        server = server_with_rate_limited_tool
        client = MCPTestClient(server)
        for _ in range(3):
            await client.call_tool("ping", {})
        result = await client.call_tool("ping", {})
        assert "Rate limit exceeded" in result

    async def test_rate_limited_tool_tracks_telemetry(self, server_with_rate_limited_tool):
        server = server_with_rate_limited_tool
        client = MCPTestClient(server)
        await client.call_tool("ping", {})
        assert len(server.telemetry.spans) >= 1


class TestToolRegistration:
    async def test_register_standard_tool(self):
        server = EnhancedMCP("reg-test")

        @server.tool()
        async def add(a: int, b: int) -> str:
            return str(a + b)

        client = MCPTestClient(server)
        result = await client.call_tool("add", {"a": 2, "b": 3})
        assert result == "5"

    async def test_list_tools(self):
        server = EnhancedMCP("list-test")

        @server.tool()
        async def tool_a() -> str:
            return "a"

        @server.tool()
        async def tool_b() -> str:
            return "b"

        client = MCPTestClient(server)
        tools = await client.list_tools()
        names = {t["name"] for t in tools}
        assert "tool_a" in names
        assert "tool_b" in names
