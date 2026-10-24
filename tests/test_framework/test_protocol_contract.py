"""Guard decorators over the real MCP protocol (in-memory client session).

A refusal must reach the client as ``isError`` and the handler must not run.
These tests go through ``ClientSession`` rather than calling the function directly.
"""

import time

import jwt
import pytest
from mcp.server.fastmcp.exceptions import ToolError
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from mcp_toolkit.framework.auth import JWTAuth
from mcp_toolkit.framework.base_server import EnhancedMCP
from mcp_toolkit.framework.testing import MCPTestClient

SECRET = "contract-test-secret-at-least-32-bytes"


def _token(scope: str = "orders:read", *, exp: float | None = None, with_exp: bool = True) -> str:
    claims: dict = {"sub": "agent-1", "scope": scope}
    if with_exp:
        claims["exp"] = time.time() + 3600 if exp is None else exp
    return jwt.encode(claims, SECRET, algorithm="HS256")


@pytest.fixture
def guarded():
    server = EnhancedMCP("contract")
    calls = {"n": 0}

    @server.auth_tool(JWTAuth(secret=SECRET), required_scope="orders:read")
    async def get_order(order_id: str, token: str = "") -> str:
        calls["n"] += 1
        return f"order {order_id}"

    return server, calls


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("forged.token.value", "Unauthorized: malformed token"),
        (_token(exp=time.time() - 3600), "Unauthorized: token expired"),
        (_token(with_exp=False), "Unauthorized: token missing required claim"),
        (_token(scope="orders:write"), "Forbidden: scope orders:read required"),
        ("", "Unauthorized: missing token"),
    ],
    ids=["forged", "expired", "no-exp", "wrong-scope", "empty"],
)
async def test_auth_refusals_are_iserror_and_handler_never_runs(guarded, token, expected):
    server, calls = guarded
    result = await MCPTestClient(server).call_tool_result(
        "get_order", {"order_id": "42", "token": token}
    )
    assert result.isError is True
    assert expected in result.content[0].text
    assert calls["n"] == 0


async def test_valid_token_is_not_an_error(guarded):
    server, calls = guarded
    result = await MCPTestClient(server).call_tool_result(
        "get_order", {"order_id": "42", "token": _token()}
    )
    assert result.isError is False
    assert result.content[0].text == "order 42"
    assert calls["n"] == 1


async def test_refusal_does_not_echo_caller_scopes(guarded):
    server, _ = guarded
    result = await MCPTestClient(server).call_tool_result(
        "get_order", {"order_id": "1", "token": _token(scope="orders:write secret:scope")}
    )
    assert "secret:scope" not in result.content[0].text
    assert "orders:write" not in result.content[0].text


async def test_rate_limit_overflow_is_iserror_and_handler_runs_only_up_to_limit():
    server = EnhancedMCP("rate")
    calls = {"n": 0}

    @server.rate_limited_tool(max_calls=2, window_seconds=60)
    async def ping(caller_id: str = "a") -> str:
        calls["n"] += 1
        return "pong"

    client = MCPTestClient(server)
    first = [await client.call_tool_result("ping", {}) for _ in range(2)]
    assert [r.isError for r in first] == [False, False]
    over = await client.call_tool_result("ping", {})
    assert over.isError is True
    assert "Rate limited: retry after 60s" in over.content[0].text
    assert calls["n"] == 2


async def _list(server):
    async with create_connected_server_and_client_session(server) as session:
        return {t.name: t for t in (await session.list_tools()).tools}


async def test_annotations_and_metadata_pass_through_every_decorator():
    server = EnhancedMCP("meta")
    hint = ToolAnnotations(readOnlyHint=True, title="Read only")

    @server.cached_tool(ttl=10, name="cached_renamed", description="cached d", annotations=hint)
    async def a() -> str:
        return "a"

    @server.rate_limited_tool(
        max_calls=5, window_seconds=1, title="Rate title", annotations=hint
    )
    async def b() -> str:
        return "b"

    @server.auth_tool(
        JWTAuth(secret=SECRET), required_scope="x", description="auth d", annotations=hint
    )
    async def c(token: str = "") -> str:
        return "c"

    tools = await _list(server)
    assert set(tools) == {"cached_renamed", "b", "c"}
    assert tools["cached_renamed"].description == "cached d"
    assert tools["b"].title == "Rate title"
    assert tools["c"].description == "auth d"
    for tool in tools.values():
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True


async def test_double_registration_raises_value_error():
    server = EnhancedMCP("dup")

    @server.cached_tool()
    async def lookup() -> str:
        return "x"

    with pytest.raises(ValueError, match="already registered"):

        @server.rate_limited_tool()
        async def lookup() -> str:  # noqa: F811
            return "y"

    with pytest.raises(ValueError, match="already registered"):

        @server.auth_tool(JWTAuth(secret=SECRET), name="lookup")
        async def other(token: str = "") -> str:
            return "z"

    # Rejected registrations leave the first tool intact.
    assert set(await _list(server)) == {"lookup"}


async def test_plain_tool_name_collision_is_also_detected():
    server = EnhancedMCP("dup2")

    @server.tool()
    async def lookup() -> str:
        return "x"

    with pytest.raises(ValueError, match="already registered"):

        @server.cached_tool()
        async def lookup() -> str:  # noqa: F811
            return "y"


class Order(BaseModel):
    id: str
    total: float


async def test_structured_output_through_a_toolkit_decorator():
    server = EnhancedMCP("structured")

    @server.auth_tool(JWTAuth(secret=SECRET), required_scope="orders:read", structured_output=True)
    async def get_order(order_id: str, token: str = "") -> Order:
        if order_id == "bad":
            return {"id": "bad"}  # type: ignore[return-value]  # missing total
        return Order(id=order_id, total=9.5)

    tools = await _list(server)
    schema = tools["get_order"].outputSchema
    assert schema is not None
    assert set(schema["properties"]) == {"id", "total"}

    client = MCPTestClient(server)
    ok = await client.call_tool_result("get_order", {"order_id": "7", "token": _token()})
    assert ok.isError is False
    assert ok.structuredContent == {"id": "7", "total": 9.5}

    bad = await client.call_tool_result("get_order", {"order_id": "bad", "token": _token()})
    assert bad.isError is True


async def test_in_process_call_tool_still_raises_tool_error(guarded):
    server, calls = guarded
    with pytest.raises(ToolError, match="Unauthorized:"):
        await MCPTestClient(server).call_tool("get_order", {"order_id": "1", "token": "x"})
    assert calls["n"] == 0


def test_jwt_requires_exp():
    import asyncio

    auth = JWTAuth(secret=SECRET)
    result = asyncio.run(auth.authenticate(_token(with_exp=False)))
    assert result.authenticated is False
    assert result.error == "Token missing required claim"


def test_jwks_mode_requires_audience_unless_opted_out():
    uri = "https://idp.example/.well-known/jwks.json"
    with pytest.raises(ValueError, match="audience"):
        JWTAuth(jwks_uri=uri)
    JWTAuth(jwks_uri=uri, audience="api://orders")
    JWTAuth(jwks_uri=uri, allow_any_audience=True)


def test_hs256_without_audience_warns_once_per_instance(caplog):
    with caplog.at_level("WARNING", logger="mcp_toolkit.framework.auth"):
        JWTAuth(secret=SECRET)
        JWTAuth(secret=SECRET)
        JWTAuth(secret=SECRET, audience="api://orders")
    warnings = [r for r in caplog.records if "audience" in r.getMessage()]
    assert len(warnings) == 2


def test_unexpected_jwt_error_text_is_not_echoed():
    from mcp_toolkit.framework.auth import _jwt_error_message

    assert _jwt_error_message(RuntimeError("secret detail 123")) == "Token validation failed"


def test_readme_hero_handles_a_forged_token():
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    readme = (root / "README.md").read_text()
    snippet = readme.split("```python\n", 1)[1].split("```", 1)[0]
    result = subprocess.run(
        [sys.executable, "-c", snippet], cwd=root, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "order 42: shipped" in result.stdout
    assert "Unauthorized: malformed token" in result.stdout
