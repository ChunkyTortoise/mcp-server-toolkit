"""The guarded-tool example from the README, runnable as-is.

Run: uv run python examples/guarded_tool.py
"""

import asyncio

import jwt
from mcp.server.mcpserver.exceptions import ToolError

from mcp_toolkit import EnhancedMCP, JWTAuth, MCPTestClient

SECRET = "replace-with-a-32-byte-or-longer-secret"
auth = JWTAuth(secret=SECRET)  # or JWTAuth(jwks_uri=..., audience=..., issuer=...) for RS256
mcp = EnhancedMCP("orders")


@mcp.auth_tool(auth, required_scope="orders:read")
async def get_order(order_id: str, token: str = "") -> str:
    return f"order {order_id}: shipped"


async def main():
    client = MCPTestClient(mcp)  # in-process MCP dispatch, no transport
    token = jwt.encode(
        {"sub": "agent-1", "scope": "orders:read", "exp": 4102444800}, SECRET, algorithm="HS256"
    )
    print(await client.call_tool("get_order", {"order_id": "42", "token": token}))
    try:
        await client.call_tool("get_order", {"order_id": "42", "token": "forged"})
    except ToolError as exc:
        print(exc)


asyncio.run(main())
