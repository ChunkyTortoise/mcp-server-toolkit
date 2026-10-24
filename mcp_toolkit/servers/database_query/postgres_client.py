"""PostgresClient - production asyncpg client with sqlglot read-only enforcement.

Requires: pip install mcp-server-toolkit[database]
  asyncpg>=0.30
  sqlglot>=26

Enforces read-only access with the shared sqlglot AST allowlist in sql_safety.py
(validate_read_only). This is defense in depth, not a security boundary: also connect
with a read-only Postgres role (for example default_transaction_read_only = on).
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

from mcp_toolkit.servers.database_query.sql_safety import validate_identifier, validate_read_only

logger = logging.getLogger(__name__)

# Kept so existing imports of the private name keep working.
_validate_read_only = validate_read_only


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
            validate_read_only(sql)

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
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """pgvector similarity search using cosine distance (<=>).

        table, embedding_column and the filter keys must be plain identifiers; they are
        double-quoted in the SQL. Filter values are bound parameters, rendered as
        ``"col" = $n`` from $3 ($1 is the vector, $2 is top_k). The final SQL goes
        through validate_read_only before it runs.

        Requires the pgvector extension: CREATE EXTENSION IF NOT EXISTS vector;
        """
        validate_identifier(table, "table name")
        validate_identifier(embedding_column, "embedding column")
        conditions: list[str] = []
        params: list[Any] = []
        for key, value in (filters or {}).items():
            validate_identifier(key, "filter column")
            params.append(value)
            conditions.append(f'"{key}" = ${len(params) + 2}')
        where = f"WHERE {' AND '.join(conditions)} " if conditions else ""
        # Identifiers are validated and quoted above; values stay bound parameters.
        sql = (
            f'SELECT *, 1 - ("{embedding_column}" <=> $1::vector) AS similarity '  # noqa: S608
            f'FROM "{table}" {where}ORDER BY similarity DESC LIMIT $2'
        )
        validate_read_only(sql)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, query_vector, top_k, *params)
            return [dict(row) for row in rows]
