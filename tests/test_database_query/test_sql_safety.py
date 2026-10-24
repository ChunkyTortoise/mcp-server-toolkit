"""One read-only validator on every path: same verdict from fetch, SQLGenerator and the helper."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("sqlglot")

from mcp_toolkit.servers.database_query import postgres_client, schema_inspector, sql_safety
from mcp_toolkit.servers.database_query.postgres_client import PostgresClient
from mcp_toolkit.servers.database_query.sql_generator import SQLGenerator
from mcp_toolkit.servers.database_query.sql_safety import (
    _DENIED_FUNCTIONS,
    validate_identifier,
    validate_read_only,
)
from tests.test_database_query.test_postgres_client import ALLOWED_SQL, HOSTILE_SQL


class FakeConn:
    def __init__(self, log: list[tuple[str, tuple[Any, ...]]]) -> None:
        self._log = log

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        self._log.append((sql, args))
        return []


class FakePool:
    """Records every statement that reaches the connection."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def acquire(self) -> "FakePool":
        return self

    async def __aenter__(self) -> FakeConn:
        return FakeConn(self.executed)

    async def __aexit__(self, *exc: object) -> None:
        return None


async def _fetch_verdict(sql: str) -> bool:
    pool = FakePool()
    try:
        await PostgresClient(pool=pool, read_only=True).fetch(sql)
    except ValueError:
        assert pool.executed == []
        return False
    assert len(pool.executed) == 1
    return True


@pytest.mark.parametrize("sql", HOSTILE_SQL + ALLOWED_SQL)
async def test_fetch_and_sql_generator_agree(sql):
    generator_verdict, _ = SQLGenerator().validate(sql)
    assert generator_verdict == await _fetch_verdict(sql)


@pytest.mark.parametrize("sql", HOSTILE_SQL)
def test_hostile_rejected_by_sql_generator(sql):
    is_valid, error = SQLGenerator().validate(sql)
    assert not is_valid
    assert error


@pytest.mark.parametrize("sql", ALLOWED_SQL)
def test_allowed_returns_checked_string_unchanged(sql):
    assert SQLGenerator().validate(sql) == (True, sql)


def test_pgvector_operator_survives_validation():
    sql = "SELECT id FROM docs ORDER BY embedding <=> '[1,2,3]'::vector LIMIT 5"
    assert SQLGenerator().validate(sql) == (True, sql)


def test_sql_generator_accepts_explain_without_analyze():
    assert SQLGenerator().validate("EXPLAIN SELECT 1")[0] is True
    assert SQLGenerator().validate("EXPLAIN ANALYZE SELECT 1")[0] is False


def test_legacy_aliases_point_at_shared_functions():
    assert postgres_client._validate_read_only is validate_read_only
    assert schema_inspector._validate_identifier is validate_identifier


# Functions the denylist must reject through both validators, called plainly and schema-qualified.
@pytest.mark.parametrize(
    "call",
    [
        "pg_write_file('/tmp/x', 'd')",
        "lo_get(1)",
        "lo_from_bytea(0, 'x')",
        "pg_read_binary_file('/etc/passwd')",
        "pg_read_file('/etc/passwd')",
        "lo_import('/etc/passwd')",
        "lo_export(1, '/tmp/x')",
        "lo_open(1, 262144)",
        "loread(0, 10)",
        "lowrite(0, 'x')",
        "pg_ls_logdir()",
        "pg_logical_slot_get_changes('s', NULL, NULL)",
        "dblink_connect_u('host=x')",
        "pg_notify('c', 'p')",
        "database_to_xml(true, true, '')",
    ],
)
def test_denied_function_rejected_by_both_validators(call):
    for sql in (f"SELECT {call}", f"SELECT pg_catalog.{call}"):
        with pytest.raises(ValueError, match="Read-only mode"):
            validate_read_only(sql)
        assert SQLGenerator().validate(sql)[0] is False


def test_every_denied_function_is_rejected_and_lowercase():
    for name in sorted(_DENIED_FUNCTIONS):
        assert name == name.lower()
        with pytest.raises(ValueError, match="Read-only mode"):
            validate_read_only(f"SELECT {name}()")
        assert SQLGenerator().validate(f"SELECT {name}()")[0] is False


def test_function_not_on_denylist_passes_the_validator():
    """The list is fixed: the database role's grants must stop everything else."""
    assert sql_safety._DENIED_FUNCTIONS.isdisjoint({"leak"})
    validate_read_only("SELECT leak()")


# ---------------------------------------------------------------------------
# vector_search
# ---------------------------------------------------------------------------


async def _search(**kwargs: Any) -> FakePool:
    pool = FakePool()
    base: dict[str, Any] = {
        "table": "docs",
        "embedding_column": "embedding",
        "query_vector": [0.1, 0.2],
    }
    await PostgresClient(pool=pool).vector_search(**{**base, **kwargs})
    return pool


async def test_vector_search_quotes_identifiers_and_numbers_placeholders_from_3():
    pool = await _search(top_k=3, filters={"tenant": "a", "kind": "faq"})
    ((sql, args),) = pool.executed
    assert sql == (
        'SELECT *, 1 - ("embedding" <=> $1::vector) AS similarity FROM "docs" '
        'WHERE "tenant" = $3 AND "kind" = $4 ORDER BY similarity DESC LIMIT $2'
    )
    assert args == ([0.1, 0.2], 3, "a", "faq")


@pytest.mark.parametrize("filters", [None, {}])
async def test_vector_search_without_filters_has_no_where(filters):
    pool = await _search(filters=filters)
    ((sql, args),) = pool.executed
    assert "WHERE" not in sql
    assert args == ([0.1, 0.2], 5)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"table": "docs; DROP TABLE users"},
        {"table": 'docs" UNION SELECT 1 --'},
        {"table": ""},
        {"embedding_column": "embedding) FROM users; DELETE FROM users --"},
        {"embedding_column": 'e"'},
        {"filters": {"a = 1 OR 1=1 --": "x"}},
        {"filters": {'a"': "x"}},
        {"filters": {"ok": 1, "bad key": 2}},
    ],
)
async def test_vector_search_rejects_malicious_identifiers_without_executing(kwargs):
    pool = FakePool()
    base: dict[str, Any] = {"table": "docs", "embedding_column": "embedding", "query_vector": [0.1]}
    with pytest.raises(ValueError, match="Invalid"):
        await PostgresClient(pool=pool).vector_search(**{**base, **kwargs})
    assert pool.executed == []


async def test_vector_search_filter_value_is_bound_not_interpolated():
    pool = await _search(filters={"tenant": "x'; DROP TABLE users; --"})
    ((sql, args),) = pool.executed
    assert "DROP" not in sql
    assert args[2] == "x'; DROP TABLE users; --"
