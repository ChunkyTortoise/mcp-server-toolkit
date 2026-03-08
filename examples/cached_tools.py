"""MCP server with caching — expensive operations cached automatically."""

import asyncio

from mcp_toolkit import EnhancedMCP

mcp = EnhancedMCP("cached-assistant")


@mcp.cached_tool(ttl=300)
async def get_weather(city: str) -> dict:
    """Fetch weather data (cached for 5 minutes)."""
    await asyncio.sleep(0.1)  # simulate latency
    return {
        "city": city,
        "temp_f": 72,
        "condition": "sunny",
        "humidity": 45,
        "cached": True,
    }


@mcp.cached_tool(ttl=60)
async def get_stock_price(ticker: str) -> dict:
    """Look up stock price (cached for 60 seconds)."""
    await asyncio.sleep(0.05)  # simulate latency
    return {"ticker": ticker.upper(), "price": 150.00, "currency": "USD"}


if __name__ == "__main__":
    mcp.run()
