"""Tests for PostgresClient — read-only enforcement (unit) + integration (INTEGRATION=1)."""

from __future__ import annotations

import os

import pytest

from mcp_toolkit.servers.database_query.postgres_client import PostgresClient, _validate_read_only


# ---------------------------------------------------------------------------
# Unit tests: sqlglot read-only validator
# ---------------------------------------------------------------------------

class TestValidateReadOnly:
    def test_allows_select(self):
        _validate_read_only("SELECT id, name FROM users WHERE active = true")

    def test_allows_cte_select(self):
        _validate_read_only("WITH t AS (SELECT 1 AS n) SELECT n FROM t")

    def test_allows_explain(self):
        _validate_read_only("EXPLAIN SELECT * FROM orders")

    def test_blocks_insert(self):
        with pytest.raises(ValueError, match="Insert"):
            _validate_read_only("INSERT INTO users (name) VALUES ('x')")

    def test_blocks_update(self):
        with pytest.raises(ValueError, match="Update"):
            _validate_read_only("UPDATE users SET name = 'y' WHERE id = 1")

    def test_blocks_delete(self):
        with pytest.raises(ValueError, match="Delete"):
            _validate_read_only("DELETE FROM users WHERE id = 1")

    def test_blocks_drop(self):
        with pytest.raises(ValueError, match="Drop"):
            _validate_read_only("DROP TABLE users")

    def test_blocks_create(self):
        with pytest.raises(ValueError, match="Create"):
            _validate_read_only("CREATE TABLE foo (id INT)")

    def test_blocks_alter(self):
        with pytest.raises(ValueError, match="Alter"):
            _validate_read_only("ALTER TABLE users ADD COLUMN age INT")

    def test_blocks_truncate(self):
        with pytest.raises(ValueError, match="Truncate"):
            _validate_read_only("TRUNCATE TABLE logs")

    def test_blocks_multi_statement_with_write(self):
        with pytest.raises(ValueError):
            _validate_read_only("SELECT 1; DELETE FROM users WHERE id = 1")


# ---------------------------------------------------------------------------
# Unit tests: PostgresClient.execute() blocked in read-only mode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_blocked_in_read_only_mode():
    client = PostgresClient(pool=None, read_only=True)
    with pytest.raises(PermissionError, match="[Rr]ead.only"):
        await client.execute("DELETE FROM users")


# ---------------------------------------------------------------------------
# Integration tests (skipped unless INTEGRATION=1)
# ---------------------------------------------------------------------------

INTEGRATION = os.environ.get("INTEGRATION") == "1"
DATABASE_URL = os.environ.get("DATABASE_URL", "")

pytestmark_integration = pytest.mark.skipif(
    not INTEGRATION or not DATABASE_URL,
    reason="Set INTEGRATION=1 and DATABASE_URL to run integration tests",
)


@pytest.mark.asyncio
@pytestmark_integration
async def test_integration_fetch_select():
    import asyncpg
    pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=1, max_size=2)
    client = PostgresClient(pool=pool, read_only=True)
    rows = await client.fetch("SELECT 1 AS n")
    assert rows == [{"n": 1}]
    await pool.close()


@pytest.mark.asyncio
@pytestmark_integration
async def test_integration_read_only_blocks_write():
    import asyncpg
    pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=1, max_size=2)
    client = PostgresClient(pool=pool, read_only=True)
    with pytest.raises(ValueError):
        await client.fetch("INSERT INTO _test_table (val) VALUES (1)")
    await pool.close()
