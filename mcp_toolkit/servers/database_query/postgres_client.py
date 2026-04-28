"""PostgresClient — production asyncpg client with sqlglot read-only enforcement.

Requires: pip install mcp-server-toolkit[database]
  asyncpg>=0.30
  sqlglot>=26

Enforces read-only access by rejecting any SQL that contains DML/DDL statements
(INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE) via sqlglot AST parsing.
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
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# SQL statement types that are never allowed in read-only mode.
_WRITE_STATEMENT_TYPES = {
    "Insert", "Update", "Delete", "Drop", "Create", "Alter", "Truncate", "TruncateTable",
    "Merge", "Replace", "Grant", "Revoke", "Lock", "Call",
}


def _validate_read_only(sql: str) -> None:
    """Raise ValueError if sql contains any write or DDL statements."""
    try:
        import sqlglot
    except ImportError as exc:
        raise ImportError("Install sqlglot: pip install mcp-server-toolkit[database]") from exc

    for statement in sqlglot.parse(sql):
        if statement is None:
            continue
        stmt_type = type(statement).__name__
        if stmt_type in _WRITE_STATEMENT_TYPES:
            raise ValueError(
                f"Read-only mode: statement type '{stmt_type}' is not allowed."
            )
        # Block any sub-expressions that are DML (e.g., CTEs wrapping INSERT)
        for node in statement.walk():
            if type(node).__name__ in _WRITE_STATEMENT_TYPES:
                raise ValueError(
                    f"Read-only mode: nested '{type(node).__name__}' not allowed."
                )


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
