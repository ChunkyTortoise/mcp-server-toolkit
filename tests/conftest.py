"""Shared test fixtures for MCP server toolkit tests."""

from __future__ import annotations

import pytest

from mcp_toolkit.framework.auth import APIKeyAuth, OAuthAuth
from mcp_toolkit.framework.base_server import EnhancedMCP
from mcp_toolkit.framework.caching import CacheLayer, InMemoryCache
from mcp_toolkit.framework.rate_limiter import RateLimiter
from mcp_toolkit.framework.telemetry import TelemetryProvider


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
