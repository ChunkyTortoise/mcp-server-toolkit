"""Basic MCP server example — minimal setup to get started."""

from mcp_toolkit import EnhancedMCP

mcp = EnhancedMCP("my-assistant")


@mcp.tool()
async def add(a: float, b: float) -> float:
    """Add two numbers and return the result."""
    return a + b


@mcp.tool()
async def greet(name: str) -> str:
    """Return a friendly greeting."""
    return f"Hello, {name}! Welcome to MCP."


if __name__ == "__main__":
    mcp.run()
