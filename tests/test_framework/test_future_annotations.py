"""Toolkit decorators under ``from __future__ import annotations``.

With the future import every annotation is a string. FastMCP resolves them with
``inspect.signature(eval_str=True)``, which follows ``__wrapped__`` back to the user
function, so names resolve in the user's module rather than in base_server.
The return model must be defined at module level; a class local to a function
cannot be resolved by any decorator, plain ``FastMCP.tool`` included.
"""

from __future__ import annotations

import time

import jwt
import pytest
from pydantic import BaseModel

from mcp_toolkit.framework.auth import JWTAuth
from mcp_toolkit.framework.base_server import EnhancedMCP
from mcp_toolkit.framework.testing import MCPTestClient

SECRET = "future-annotations-secret-at-least-32-bytes"


class Row(BaseModel):
    n: int


def _build() -> EnhancedMCP:
    server = EnhancedMCP("future")

    @server.cached_tool(ttl=5)
    async def cached_row(n: int) -> Row:
        return Row(n=n)

    @server.rate_limited_tool(max_calls=5)
    async def limited_row(n: int) -> Row:
        return Row(n=n)

    @server.auth_tool(JWTAuth(secret=SECRET), required_scope="rows:read")
    async def auth_row(n: int, token: str = "") -> Row:
        return Row(n=n)

    return server


@pytest.mark.parametrize("tool", ["cached_row", "limited_row", "auth_row"])
async def test_string_annotations_resolve_to_user_module_model(tool):
    server = _build()
    assert server._tool_manager.get_tool(tool).output_schema["title"] == "Row"

    args: dict = {"n": 3}
    if tool == "auth_row":
        args["token"] = jwt.encode(
            {"sub": "a", "scope": "rows:read", "exp": time.time() + 60}, SECRET, algorithm="HS256"
        )
    result = await MCPTestClient(server).call_tool_result(tool, args)
    assert result.isError is False
    assert result.structuredContent == {"n": 3}
