"""Tests for MCPTestClient utility."""

import pytest

from mcp_toolkit.framework.base_server import EnhancedMCP
from mcp_toolkit.framework.testing import MCPTestClient


class TestMCPTestClient:
    @pytest.fixture
    def server_and_client(self):
        server = EnhancedMCP("test-client-server")

        @server.tool()
        async def echo(message: str) -> str:
            """Echo the message back."""
            return f"Echo: {message}"

        @server.tool()
        async def add_numbers(a: int, b: int) -> str:
            """Add two numbers."""
            return str(a + b)

        client = MCPTestClient(server)
        return server, client

    async def test_call_tool(self, server_and_client):
        _, client = server_and_client
        result = await client.call_tool("echo", {"message": "Hello"})
        assert result == "Echo: Hello"

    async def test_call_tool_with_multiple_args(self, server_and_client):
        _, client = server_and_client
        result = await client.call_tool("add_numbers", {"a": 5, "b": 3})
        assert result == "8"

    async def test_list_tools(self, server_and_client):
        _, client = server_and_client
        tools = await client.list_tools()
        assert len(tools) >= 2
        names = {t["name"] for t in tools}
        assert "echo" in names
        assert "add_numbers" in names

    async def test_tool_has_description(self, server_and_client):
        _, client = server_and_client
        tools = await client.list_tools()
        echo_tool = next(t for t in tools if t["name"] == "echo")
        assert "Echo the message back" in echo_tool["description"]

    async def test_call_tool_empty_args(self):
        server = EnhancedMCP("no-args")

        @server.tool()
        async def ping() -> str:
            return "pong"

        client = MCPTestClient(server)
        result = await client.call_tool("ping")
        assert result == "pong"

    async def test_call_tool_default_empty_dict(self):
        server = EnhancedMCP("default")

        @server.tool()
        async def status() -> str:
            return "ok"

        client = MCPTestClient(server)
        result = await client.call_tool("status", None)
        assert result == "ok"
