"""PostgresClient — production asyncpg client with sqlglot read-only enforcement.

Requires: pip install mcp-server-toolkit[database]
  asyncpg>=0.30
  sqlglot>=26

Enforces read-only access with a sqlglot AST allowlist: only SELECT, set operations
(UNION/INTERSECT/EXCEPT), VALUES and a non-executing EXPLAIN are accepted. DML/DDL
anywhere in the tree, SELECT ... INTO, COPY, statements sqlglot cannot parse, and
known side-effecting functions (file access, backend control, dblink, set_config)
are rejected. This is defense in depth, not a security boundary: also connect with
a read-only Postgres role (for example default_transaction_read_only = on).
Supports pgvector similarity search when the vector extension is installed.

Usage:
    import asyncpg
    from mcp_toolkit.servers.database_query.postgres_client import PostgresClient
    from mcp_toolkit.servers.database_query import server as db_server

    pool = await asyncpg.create_pool(dsn=os.environ["DATABASE_URL"])
    client = PostgresClient(pool=pool, read_only=True)
    db_server.configure(db_connection=client)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# SQL statement types that are never allowed in read-only mode.
_WRITE_STATEMENT_TYPES = {
    "Insert", "Update", "Delete", "Drop", "Create", "Alter", "Truncate", "TruncateTable",
    "Merge", "Replace", "Grant", "Revoke", "Lock", "Call",
}

# Top-level statement types accepted in read-only mode (allowlist).
_ALLOWED_STATEMENT_TYPES = {"Select", "Union", "Intersect", "Except", "Values"}

# Node types rejected anywhere in the tree, in addition to the write statements.
# Into: SELECT ... INTO creates a table. Copy: COPY ... TO PROGRAM runs a shell
# command. Command: SQL sqlglot could not parse (SET ROLE, VACUUM, ...).
_DENIED_NODE_TYPES = _WRITE_STATEMENT_TYPES | {"Into", "Copy", "Command", "Set"}

# Functions with side effects or file/network access that a SELECT can call.
_DENIED_FUNCTIONS = {
    "pg_terminate_backend", "pg_cancel_backend", "pg_reload_conf", "pg_rotate_logfile",
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file",
    "lo_import", "lo_export", "lo_unlink", "lo_create", "lo_put",
    "dblink", "dblink_exec", "dblink_connect", "dblink_send_query",
    "set_config", "pg_sleep", "pg_advisory_lock", "pg_advisory_xact_lock",
    "nextval", "setval", "pg_switch_wal", "pg_create_restore_point", "pg_promote",
    "query_to_xml", "query_to_xmlschema", "query_to_xml_and_xmlschema", "cursor_to_xml",
}

_EXPLAIN_OPTIONS = re.compile(r"^\s*(?:\([^)]*\)|(?:VERBOSE|COSTS|BUFFERS|FORMAT\s+\w+)\s+)*", re.IGNORECASE)
_EXPLAIN_ANALYZE = re.compile(r"\bANALY[SZ]E\b", re.IGNORECASE)


def _reject(reason: str) -> None:
    raise ValueError(f"Read-only mode: {reason} is not allowed.")


def _validate_explain(rest: str) -> None:
    """EXPLAIN is allowed only without ANALYZE (which executes the statement)."""
    if _EXPLAIN_ANALYZE.search(rest):
        _reject("EXPLAIN ANALYZE")
    _validate_read_only(_EXPLAIN_OPTIONS.sub("", rest, count=1))


def _validate_read_only(sql: str) -> None:
    """Raise ValueError unless every statement in sql is a plain read."""
    try:
        import sqlglot
        from sqlglot import exp
    except ImportError as exc:
        raise ImportError("Install sqlglot: pip install mcp-server-toolkit[database]") from exc

    statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    if not statements:
        _reject("an empty statement")
    for statement in statements:
        stmt_type = type(statement).__name__
        if isinstance(statement, exp.Command) and str(statement.this).upper() == "EXPLAIN":
            rest = statement.expression
            _validate_explain(str(getattr(rest, "name", rest) or ""))
            continue
        if stmt_type not in _ALLOWED_STATEMENT_TYPES:
            _reject(f"statement type '{stmt_type}'")
        for node in statement.walk():
            node_type = type(node).__name__
            if node_type in _DENIED_NODE_TYPES:
                _reject(f"nested '{node_type}'")
            if isinstance(node, exp.Func):
                name = node.name if isinstance(node, exp.Anonymous) else node.sql_name()
                if name and name.lower() in _DENIED_FUNCTIONS:
                    _reject(f"function '{name.lower()}'")


@dataclass
class PostgresClient:
    """asyncpg-backed database client with optional read-only enforcement.

    Pass this as ``db_connection`` to ``database_query.server.configure()``.
    The server calls ``client.fetch(sql)`` for query execution and
    ``client.fetch(schema_query)`` for schema introspection.
    """

    pool: Any
    read_only: bool = True

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        """Execute sql and return rows as list[dict]. Validates read-only if enabled."""
        if self.read_only:
            _validate_read_only(sql)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
            return [dict(row) for row in rows]

    async def execute(self, sql: str, *args: Any) -> str:
        """Execute a non-returning statement (write operations must be explicitly unlocked)."""
        if self.read_only:
            raise PermissionError("Read-only mode: execute() is disabled. Set read_only=False.")
        async with self.pool.acquire() as conn:
            return await conn.execute(sql, *args)

    async def vector_search(
        self,
        table: str,
        embedding_column: str,
        query_vector: list[float],
        top_k: int = 5,
        filter_clause: str = "",
    ) -> list[dict[str, Any]]:
        """pgvector similarity search using cosine distance (<=>).

        Requires the pgvector extension: CREATE EXTENSION IF NOT EXISTS vector;
        """
        where = f"WHERE {filter_clause}" if filter_clause else ""
        sql = (
            f"SELECT *, 1 - ({embedding_column} <=> $1::vector) AS similarity "
            f"FROM {table} {where} ORDER BY similarity DESC LIMIT $2"
        )
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, query_vector, top_k)
            return [dict(row) for row in rows]
