"""Shared test fixtures for MCP server toolkit tests."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

import pytest

from mcp_toolkit.framework.auth import APIKeyAuth, OAuthAuth
from mcp_toolkit.framework.base_server import EnhancedMCP
from mcp_toolkit.framework.caching import CacheLayer, InMemoryCache
from mcp_toolkit.framework.rate_limiter import RateLimiter
from mcp_toolkit.framework.telemetry import TelemetryProvider


@contextlib.contextmanager
def grant_scopes(*scopes: str) -> Iterator[None]:
    """Populate the SDK's per-request auth contextvar exactly as its
    ``AuthContextMiddleware`` does for an authenticated HTTP request, so tests
    can exercise ``@requires_scope`` tool *logic* without a live transport.

    Uses real SDK objects (``AuthenticatedUser`` / ``AccessToken``) — never a
    mock of the auth path. Outside this context the contextvar is unset, which
    is the production stdio reality (no ``Authorization`` channel -> tools
    hard-reject). See ADR-0008.
    """
    from mcp.server.auth.middleware.auth_context import auth_context_var
    from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
    from mcp.server.auth.provider import AccessToken

    user = AuthenticatedUser(
        AccessToken(
            token="test-context-token",
            client_id="test-client",
            scopes=list(scopes),
            expires_at=None,
        )
    )
    handle = auth_context_var.set(user)
    try:
        yield
    finally:
        auth_context_var.reset(handle)


def stub_tool_args(input_schema: dict) -> dict:
    """Minimal kwargs satisfying a tool's required params, so a call reaches
    an ``@requires_scope`` decorator instead of failing arg validation first.
    Used by the auth-canary tests, which discover tools via ``list_tools()``."""
    props = (input_schema or {}).get("properties", {})
    required = (input_schema or {}).get("required", [])
    stub: dict = {}
    for name in required:
        kind = props.get(name, {}).get("type", "string")
        stub[name] = 0 if kind in ("number", "integer") else "x"
    return stub


@pytest.fixture
def enhanced_mcp():
    """Create a fresh EnhancedMCP instance for testing."""
    return EnhancedMCP("test-server")


@pytest.fixture
def cache():
    """Create an in-memory cache."""
    return InMemoryCache()


@pytest.fixture
def cache_layer(cache):
    """Create a CacheLayer with in-memory backend."""
    layer = CacheLayer(backend=cache)
    layer.initialize()
    return layer


@pytest.fixture
def rate_limiter():
    """Create a rate limiter."""
    return RateLimiter()


@pytest.fixture
def telemetry():
    """Create a telemetry provider."""
    provider = TelemetryProvider("test")
    provider.initialize()
    return provider


@pytest.fixture
def api_key_auth():
    """Create an API key auth provider."""
    return APIKeyAuth()


@pytest.fixture
def oauth_auth():
    """Create an OAuth auth provider."""
    return OAuthAuth(secret="test-secret", issuer="test")


class MockDatabaseConnection:
    """Mock database connection for testing."""

    def __init__(self, tables: dict | None = None):
        self._tables = tables or {}
        self._queries: list[str] = []

    def add_table(self, name: str, columns: list[dict], rows: list[dict] | None = None):
        self._tables[name] = {"columns": columns, "rows": rows or []}

    async def fetch(self, query: str) -> list[dict]:
        self._queries.append(query)
        if "information_schema.tables" in query:
            return [{"table_name": name, "table_schema": "public"} for name in self._tables]
        if "information_schema.columns" in query:
            for name, info in self._tables.items():
                if name in query:
                    return info["columns"]
            return []
        for name, info in self._tables.items():
            if name.lower() in query.lower():
                return info["rows"]
        return []

    @property
    def queries(self) -> list[str]:
        return self._queries


@pytest.fixture
def mock_db():
    """Create a mock database connection with sample data."""
    db = MockDatabaseConnection()
    db.add_table(
        "users",
        columns=[
            {
                "column_name": "id",
                "data_type": "integer",
                "is_nullable": "NO",
                "column_default": None,
            },
            {
                "column_name": "name",
                "data_type": "varchar",
                "is_nullable": "NO",
                "column_default": None,
            },
            {
                "column_name": "email",
                "data_type": "varchar",
                "is_nullable": "NO",
                "column_default": None,
            },
            {
                "column_name": "created_at",
                "data_type": "timestamp",
                "is_nullable": "YES",
                "column_default": "now()",
            },
        ],
        rows=[
            {"id": 1, "name": "Alice", "email": "alice@test.com", "created_at": "2024-01-01"},
            {"id": 2, "name": "Bob", "email": "bob@test.com", "created_at": "2024-01-02"},
        ],
    )
    db.add_table(
        "orders",
        columns=[
            {
                "column_name": "id",
                "data_type": "integer",
                "is_nullable": "NO",
                "column_default": None,
            },
            {
                "column_name": "user_id",
                "data_type": "integer",
                "is_nullable": "NO",
                "column_default": None,
            },
            {
                "column_name": "total",
                "data_type": "numeric",
                "is_nullable": "NO",
                "column_default": None,
            },
        ],
        rows=[
            {"id": 1, "user_id": 1, "total": "100.00"},
            {"id": 2, "user_id": 2, "total": "250.00"},
        ],
    )
    return db
