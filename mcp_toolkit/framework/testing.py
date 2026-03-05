"""MCPTestClient — test utilities for MCP servers without running a real server."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP


class MCPTestClient:
    """Test client for MCP servers.

    Provides a simple interface to invoke tools, list tools, and read resources
    from an MCP server instance without network transport.

    Usage:
        server = EnhancedMCP("test-server")

        @server.tool()
        async def greet(name: str) -> str:
            return f"Hello, {name}!"

        client = MCPTestClient(server)
        result = await client.call_tool("greet", {"name": "World"})
        assert result == "Hello, World!"
    """

    def __init__(self, server: FastMCP) -> None:
        self._server = server

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call a tool by name with the given arguments.

        Returns the tool result content. If the result contains a single text content
        item, returns just the text string. Otherwise returns the full content list.
        """
        result = await self._server.call_tool(name, arguments or {})
        # MCP SDK may return (content_list, metadata_dict) tuple
        content = result
        if isinstance(result, tuple) and len(result) >= 1:
            content = result[0]
        if isinstance(content, list) and len(content) == 1 and hasattr(content[0], "text"):
            return content[0].text
        return content

    async def list_tools(self) -> list[dict[str, Any]]:
        """List all registered tools on the server.

        Returns a list of dicts with 'name', 'description', and 'inputSchema'.
        """
        tools = await self._server.list_tools()
        return [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": t.inputSchema if hasattr(t, "inputSchema") else {},
            }
            for t in tools
        ]

    async def read_resource(self, uri: str) -> Any:
        """Read a resource by URI.

        Returns the resource content as a string.
        """
        result = await self._server.read_resource(uri)
        if isinstance(result, str):
            return result
        if hasattr(result, "contents") and result.contents:
            first = result.contents[0]
            if hasattr(first, "text"):
                return first.text
        return str(result)

    async def list_resources(self) -> list[dict[str, Any]]:
        """List all registered resources."""
        resources = await self._server.list_resources()
        return [
            {
                "uri": str(r.uri) if hasattr(r, "uri") else str(r),
                "name": r.name if hasattr(r, "name") else "",
            }
            for r in resources
        ]
