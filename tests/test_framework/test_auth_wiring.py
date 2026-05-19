"""End-to-end auth-wiring proof for the auth-enabled servers.

This is the gate for the audit's harshest finding (credential read from a
public tool-schema parameter). Two layers of proof:

1. **Schema gate** — no auth-wired tool's ``inputSchema`` exposes a
   ``token`` / ``api_key`` / ``authorization`` property. If this fails the
   credential is still caller-supplied public input and nothing else matters.
2. **Live transport** — the SDK's real bearer-auth middleware stack is
   exercised through ``streamable_http_app()`` (NOT mocked): no header -> 401,
   wrong scope -> 403, valid bearer -> 200 and the decorated tool runs.
"""

from __future__ import annotations

import time

import jwt
import pytest
from starlette.testclient import TestClient

from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from mcp_toolkit.framework.auth import JWTAuth, JWTTokenVerifier, requires_scope
from mcp_toolkit.framework.base_server import EnhancedMCP

FORBIDDEN_CREDENTIAL_PARAMS = {"token", "api_key", "authorization"}
_SECRET = "auth-wiring-test-secret-at-least-32-bytes"

_JSON_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}


def _bearer(scopes: list[str], secret: str = _SECRET) -> str:
    return jwt.encode(
        {"sub": "client-1", "scope": " ".join(scopes), "exp": time.time() + 3600},
        secret,
        algorithm="HS256",
    )


# ── 1. Schema gate (the audit-finding gate) ──────────────────────────────────


@pytest.mark.parametrize(
    "import_path",
    [
        "mcp_toolkit.servers.database_query.server",
        "mcp_toolkit.servers.crm_ghl.server",
    ],
)
async def test_no_tool_schema_exposes_a_credential(import_path):
    """No auth-wired tool may accept the credential as a public parameter."""
    import importlib

    server_mod = importlib.import_module(import_path)
    tools = await server_mod.mcp.list_tools()
    assert tools, f"{import_path} exposed no tools"
    for tool in tools:
        props = set((tool.inputSchema or {}).get("properties", {}))
        leaked = props & FORBIDDEN_CREDENTIAL_PARAMS
        assert not leaked, (
            f"{import_path}:{tool.name} exposes credential param(s) {leaked} "
            f"in its inputSchema — auth must come from the bearer token, not "
            f"a tool argument"
        )


# ── 2. Live SDK auth path (no mocking of the auth middleware) ────────────────


@pytest.fixture
def authed_app():
    """A real EnhancedMCP wired exactly like the shipped servers, with one
    probe tool. DNS-rebinding protection (an orthogonal SDK transport feature)
    is disabled so the Starlette TestClient host passes; the auth path itself
    is fully live."""
    mcp = EnhancedMCP(
        "auth-wiring-probe",
        token_verifier=JWTTokenVerifier(JWTAuth(secret=_SECRET)),
        auth=AuthSettings(
            issuer_url="https://example.test",
            resource_server_url="http://localhost:8000",
            required_scopes=["db:read"],
        ),
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )

    @mcp.tool()
    @requires_scope("db:read")
    async def probe() -> str:
        return "authorized-result"

    return mcp.streamable_http_app()


def test_no_authorization_header_returns_401(authed_app):
    client = TestClient(authed_app)
    r = client.post("/mcp", json=_INIT, headers=_JSON_HEADERS)
    assert r.status_code == 401
    assert "www-authenticate" in {k.lower() for k in r.headers}
    assert "Bearer" in r.headers["www-authenticate"]


def test_valid_token_missing_scope_returns_403(authed_app):
    client = TestClient(authed_app)
    r = client.post(
        "/mcp",
        json=_INIT,
        headers={**_JSON_HEADERS, "Authorization": f"Bearer {_bearer(['other:scope'])}"},
    )
    assert r.status_code == 403
    assert "insufficient_scope" in r.headers.get("www-authenticate", "")


def test_valid_bearer_token_authorizes_and_runs_tool(authed_app):
    """Valid bearer + required scope -> 200 and the @requires_scope tool body
    actually executes (proves get_access_token() saw the verified token)."""
    token = _bearer(["db:read"])
    auth_headers = {**_JSON_HEADERS, "Authorization": f"Bearer {token}"}
    with TestClient(authed_app) as client:
        init = client.post("/mcp", json=_INIT, headers=auth_headers)
        assert init.status_code == 200
        session_id = init.headers["mcp-session-id"]
        sess_headers = {**auth_headers, "mcp-session-id": session_id}
        client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=sess_headers,
        )
        call = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "probe", "arguments": {}},
            },
            headers=sess_headers,
        )
    assert call.status_code == 200
    assert "authorized-result" in call.text
    assert "Unauthorized" not in call.text
