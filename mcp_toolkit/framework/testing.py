"""MCPTestClient: test utilities for MCP servers without running a real server."""

from __future__ import annotations

from typing import Any

from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, InputRequiredResult, TextContent


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

    def __init__(self, server: MCPServer) -> None:
        self._server = server

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call a tool by name with the given arguments.

        Returns the tool result content. If the result contains a single text content
        item, returns just the text string. Otherwise returns the full content list.
        Calls the server in-process, so a tool that raises (including a guard refusal)
        re-raises ``ToolError`` here. Use :meth:`call_tool_result` to see ``is_error``.
        """
        result = await self._server.call_tool(name, arguments or {})
        content = result.content if isinstance(result, CallToolResult) else result
        if isinstance(content, list) and len(content) == 1 and isinstance(content[0], TextContent):
            return content[0].text
        return content

    async def call_tool_result(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> CallToolResult:
        """Call a tool through an in-memory MCP client session and return the raw result.

        Unlike :meth:`call_tool`, this goes over the real protocol, so a refusal or a
        tool failure comes back as ``CallToolResult`` with ``is_error`` true.
        """
        async with Client(self._server) as client:
            return await client.call_tool(name, arguments or {})

    async def list_tools(self) -> list[dict[str, Any]]:
        """List all registered tools on the server.

        Returns a list of dicts with 'name', 'description', and 'inputSchema'.
        """
        tools = await self._server.list_tools()
        return [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": t.input_schema,
            }
            for t in tools
        ]

    async def read_resource(self, uri: str) -> Any:
        """Read a resource by URI.

        Returns the resource content as a string.
        """
        result = await self._server.read_resource(uri)
        if isinstance(result, InputRequiredResult):
            return str(result)
        contents = list(result)
        if contents and isinstance(contents[0].content, str):
            return contents[0].content
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
