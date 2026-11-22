"""Tests for PostgresClient - read-only enforcement (unit) + integration (INTEGRATION=1)."""

from __future__ import annotations

import os
import time

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
# Unit tests: fetch_bounded uses a cursor in a READ ONLY transaction
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.read = 0

    async def fetchrow(self):
        if self.read == len(self.rows):
            return None
        self.read += 1
        return self.rows[self.read - 1]


class _FakeTransaction:
    def __init__(self, conn, readonly):
        self.conn = conn
        conn.transactions.append(readonly)

    async def __aenter__(self):
        self.conn.events.append("begin")

    async def __aexit__(self, *exc):
        self.conn.events.append("end")


class _FakeConn:
    def __init__(self, rows):
        self.cursor_obj = _FakeCursor(rows)
        self.transactions = []
        self.events = []
        self.cursor_sql = []
        self.executed = []

    def transaction(self, readonly=False):
        return _FakeTransaction(self, readonly)

    async def execute(self, sql):
        assert self.events == ["begin"], "SET LOCAL outside the transaction"
        assert self.cursor_sql == [], "SET LOCAL after the cursor opened"
        self.executed.append(sql)

    async def cursor(self, sql):
        assert self.events == ["begin"], "cursor opened outside the transaction"
        self.cursor_sql.append(sql)
        return self.cursor_obj

    async def fetch(self, *args):
        raise AssertionError("fetch_bounded must not fetch the whole result")


class _FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        pool = self

        class _Acquire:
            async def __aenter__(self):
                return pool.conn

            async def __aexit__(self, *exc):
                return None

        return _Acquire()


@pytest.mark.asyncio
@pytest.mark.parametrize("available, expect_truncated", [(3, False), (5, True), (500, True)])
async def test_fetch_bounded_reads_at_most_max_rows_plus_one(available, expect_truncated):
    conn = _FakeConn([{"id": i} for i in range(available)])
    rows, truncated = await PostgresClient(pool=_FakePool(conn)).fetch_bounded(
        "SELECT id FROM items", max_rows=4
    )
    assert conn.cursor_obj.read == min(available, 5)
    assert conn.transactions == [True]
    assert conn.events == ["begin", "end"]
    assert conn.executed == ["SET LOCAL statement_timeout = 5000"]
    assert len(rows) == min(available, 4)
    assert truncated is expect_truncated


@pytest.mark.asyncio
async def test_fetch_bounded_sets_the_configured_statement_timeout():
    conn = _FakeConn([{"id": 1}])
    client = PostgresClient(pool=_FakePool(conn), statement_timeout_ms=250)
    await client.fetch_bounded("SELECT 1", max_rows=10)
    assert conn.executed == ["SET LOCAL statement_timeout = 250"]


@pytest.mark.asyncio
async def test_fetch_bounded_stops_reading_at_the_byte_budget():
    """Each row is 400 bytes; a 1000-byte budget stops after the third row."""
    conn = _FakeConn([{"cell": "x" * 400} for _ in range(50)])
    client = PostgresClient(pool=_FakePool(conn), max_result_bytes=1000)
    rows, truncated = await client.fetch_bounded("SELECT cell FROM big", max_rows=100)
    assert len(rows) == 3
    assert conn.cursor_obj.read == 3
    assert truncated is True


@pytest.mark.asyncio
async def test_fetch_bounded_counts_bytes_values_and_skips_null():
    conn = _FakeConn([{"b": b"y" * 600, "n": None, "i": 12345}] * 3)
    client = PostgresClient(pool=_FakePool(conn), max_result_bytes=1000)
    rows, truncated = await client.fetch_bounded("SELECT 1", max_rows=100)
    assert len(rows) == 2 and truncated is True


@pytest.mark.parametrize("name", ["statement_timeout_ms", "max_result_bytes"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_client_limits_must_be_positive_integers(name, value):
    with pytest.raises(ValueError, match=name):
        PostgresClient(**{name: value})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; SELECT 2",
        "WITH d AS (DELETE FROM items RETURNING *) SELECT * FROM d",
        "DROP TABLE x",
    ],
)
async def test_fetch_bounded_validates_before_the_database(sql):
    conn = _FakeConn([])
    client = PostgresClient(pool=_FakePool(conn), read_only=False)
    with pytest.raises(ValueError, match="Read-only mode"):
        await client.fetch_bounded(sql, max_rows=10)
    assert conn.cursor_sql == [] and conn.transactions == []


@pytest.mark.asyncio
async def test_fetch_bounded_rejects_non_positive_limit():
    with pytest.raises(ValueError, match="max_rows"):
        await PostgresClient(pool=_FakePool(_FakeConn([]))).fetch_bounded("SELECT 1", 0)


@pytest.mark.asyncio
async def test_owned_pool_closes_after_last_user(monkeypatch):
    import asyncpg

    closed = []

    class _Pool:
        async def close(self):
            closed.append(True)

    async def create_pool(**kwargs):
        assert kwargs["dsn"] == "postgresql://reader@db.invalid/x"
        assert kwargs["server_settings"] == {"statement_timeout": "5000"}
        assert kwargs["command_timeout"] == 10
        return _Pool()

    monkeypatch.setattr(asyncpg, "create_pool", create_pool)
    client = PostgresClient(dsn="postgresql://reader@db.invalid/x")
    await client.open()
    await client.open()
    first_pool = client.pool
    await client.close()
    assert closed == [] and client.pool is first_pool
    await client.close()
    assert closed == [True] and client.pool is None


@pytest.mark.asyncio
async def test_failed_open_does_not_count_a_user(monkeypatch):
    import asyncpg

    attempts = []

    class _Pool:
        async def close(self):
            attempts.append("closed")

    async def create_pool(**kwargs):
        attempts.append("create")
        if len(attempts) == 1:
            raise OSError("db down")
        return _Pool()

    monkeypatch.setattr(asyncpg, "create_pool", create_pool)
    client = PostgresClient(dsn="postgresql://reader@db.invalid/x")
    with pytest.raises(OSError):
        await client.open()
    assert client.pool is None
    await client.open()
    await client.close()
    assert attempts == ["create", "create", "closed"] and client.pool is None


@pytest.mark.asyncio
async def test_concurrent_open_creates_one_pool(monkeypatch):
    import asyncio

    import asyncpg

    created = []

    class _Pool:
        async def close(self):
            pass

    async def create_pool(**kwargs):
        await asyncio.sleep(0.01)
        created.append(_Pool())
        return created[-1]

    monkeypatch.setattr(asyncpg, "create_pool", create_pool)
    client = PostgresClient(dsn="postgresql://reader@db.invalid/x")
    await asyncio.gather(client.open(), client.open(), client.open())
    assert len(created) == 1 and client.pool is created[0]


class _DupRecord:
    """asyncpg.Record keeps duplicate column names; dict(record) would drop one."""

    def __init__(self, items):
        self._items = items

    def items(self):
        return iter(self._items)

    def values(self):
        return iter(v for _, v in self._items)


@pytest.mark.asyncio
async def test_fetch_bounded_keeps_duplicate_column_names():
    conn = _FakeConn([_DupRecord([("id", 1), ("id", 2), ("id_2", 3)])])
    rows, _ = await PostgresClient(pool=_FakePool(conn)).fetch_bounded(
        "SELECT a.id, b.id, 3 AS id_2 FROM a, b", max_rows=5
    )
    assert rows == [{"id": 1, "id_2": 2, "id_2_2": 3}]


@pytest.mark.asyncio
async def test_caller_pool_is_never_closed():
    class _Pool:
        async def close(self):
            raise AssertionError("caller-owned pool closed")

    pool = _Pool()
    client = PostgresClient(pool=pool)
    await client.open()
    await client.close()
    assert client.pool is pool


def test_dsn_is_not_in_repr():
    assert "pw-sentinel" not in repr(PostgresClient(dsn="postgresql://u:pw-sentinel@h/x"))


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


EXPENSIVE_SQL = (
    "SELECT count(*) FROM generate_series(1, 4000) a, "
    "generate_series(1, 4000) b, generate_series(1, 4000) c"
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

    sql = EXPENSIVE_SQL
    _validate_read_only(sql)
    with pytest.raises(asyncpg.QueryCanceledError):
        await PostgresClient(pool=reader_pool).fetch(sql)


@pytestmark_integration
async def test_integration_client_statement_timeout_without_a_role_timeout(admin_pool):
    """The superuser has no role timeout, so only the client's SET LOCAL can cancel."""
    import asyncpg

    async with admin_pool.acquire() as conn:
        assert await conn.fetchval("SHOW statement_timeout") == "0"
    client = PostgresClient(pool=admin_pool, statement_timeout_ms=200)
    started = time.monotonic()
    with pytest.raises(asyncpg.QueryCanceledError):
        await client.fetch_bounded(EXPENSIVE_SQL, max_rows=1)
    assert time.monotonic() - started < 5
    async with admin_pool.acquire() as conn:
        assert await conn.fetchval("SHOW statement_timeout") == "0"  # SET LOCAL only


@pytestmark_integration
async def test_integration_owned_pool_sets_statement_timeout():
    client = PostgresClient(dsn=ADMIN_DATABASE_URL, statement_timeout_ms=750)
    await client.open()
    try:
        assert await client.fetch("SELECT current_setting('statement_timeout') AS t") == [
            {"t": "750ms"}
        ]
    finally:
        await client.close()


@pytestmark_integration
async def test_integration_byte_budget_stops_reading_huge_cells(reader_pool):
    client = PostgresClient(pool=reader_pool, max_result_bytes=3_000_000)
    rows, truncated = await client.fetch_bounded(
        "SELECT repeat('x', 1000000) AS cell FROM generate_series(1, 60)", max_rows=100
    )
    assert len(rows) == 3 and truncated is True


@pytestmark_integration
async def test_integration_ts_stat_is_refused_before_the_database(reader_pool):
    client = PostgresClient(pool=reader_pool)
    with pytest.raises(ValueError, match="ts_stat"):
        await client.fetch_bounded("SELECT * FROM ts_stat('SELECT pg_sleep(5)')", max_rows=1)


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


@pytestmark_integration
@pytest.mark.parametrize(
    "sql, table",
    [
        ("WITH x AS (INSERT INTO write_probe VALUES (1) RETURNING id) SELECT * FROM x", "write_probe"),
        ("WITH gone AS (DELETE FROM items RETURNING id) SELECT count(*) FROM gone", "items"),
    ],
)
async def test_integration_read_only_transaction_refuses_with_validator_bypassed(
    monkeypatch, admin_pool, sql, table
):
    """Third layer on its own: no validator, a superuser, only READ ONLY refuses."""
    import asyncpg

    from mcp_toolkit.servers.database_query import postgres_client

    monkeypatch.setattr(postgres_client, "validate_single_read", lambda sql: None)
    count_sql = f"SELECT count(*) FROM {table}"  # noqa: S608 (fixed test table name)
    before = await admin_pool.fetchval(count_sql)
    with pytest.raises(asyncpg.ReadOnlySQLTransactionError):
        await PostgresClient(pool=admin_pool).fetch_bounded(sql, max_rows=5)
    assert await admin_pool.fetchval(count_sql) == before


@pytestmark_integration
async def test_integration_explain_returns_the_plan(reader_pool):
    rows, truncated = await PostgresClient(pool=reader_pool).fetch_bounded(
        "EXPLAIN SELECT id FROM items WHERE id = 1", max_rows=50
    )
    assert not truncated
    assert rows and set(rows[0]) == {"QUERY PLAN"}
    assert "items" in "\n".join(r["QUERY PLAN"] for r in rows)


@pytestmark_integration
async def test_integration_not_blocked_same_role_sees_other_sessions_sql(reader_pool):
    """not blocked: pg_stat_activity shows SQL from other sessions of the same role."""
    import asyncio

    async with reader_pool.acquire() as other:
        running = asyncio.create_task(
            other.fetchval("SELECT 'pgsa-sentinel-55e1' FROM pg_sleep(1)")
        )
        await asyncio.sleep(0.3)
        rows, _ = await PostgresClient(pool=reader_pool).fetch_bounded(
            "SELECT query FROM pg_stat_activity "
            "WHERE pid <> pg_backend_pid() AND state = 'active'",
            max_rows=50,
        )
        await running
    print("not blocked: revoke pg_stat_activity or use one role per caller")
    assert any("pgsa-sentinel-55e1" in r["query"] for r in rows)
