"""PostgresClient - production asyncpg client with sqlglot read-only enforcement.

Requires: pip install mcp-server-toolkit[database]
  asyncpg>=0.30
  sqlglot>=26

Enforces read-only access with the shared sqlglot AST allowlist in sql_safety.py
(validate_read_only). This is defense in depth, not a security boundary: also connect
with a read-only Postgres role (for example default_transaction_read_only = on).
Supports pgvector similarity search when the vector extension is installed.

Usage:
    from mcp_toolkit.servers.database_query.postgres_client import PostgresClient
    from mcp_toolkit.servers.database_query.server import DatabaseServerSettings, create_server

    client = PostgresClient(dsn=os.environ["DATABASE_URL"], read_only=True)
    server = create_server(DatabaseServerSettings(), client)

The server lifespan calls open() and close(). A pool passed in by the caller is
used as is and never closed here.

Every fetch_bounded transaction sets ``statement_timeout`` (SET LOCAL), so a slow
query is cancelled by the server even when the role has no timeout of its own. An
owned pool also gets it as a session default plus an asyncpg command_timeout.
Results are read one row at a time against a byte budget (max_result_bytes), so a
query that returns huge cells stops early. One row is still read in full: a single
cell larger than the budget is held in memory once before the fetch stops.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from mcp_toolkit.servers.database_query.sql_safety import (
    validate_identifier,
    validate_read_only,
    validate_single_read,
)

logger = logging.getLogger(__name__)

# Kept so existing imports of the private name keep working.
_validate_read_only = validate_read_only


def _row_size(row: Any) -> int:
    """Approximate bytes of one row: text and binary lengths, others as their str()."""
    total = 0
    for value in row.values():
        if isinstance(value, (str, bytes, bytearray, memoryview)):
            total += len(value)
        elif value is not None:
            total += len(str(value))
    return total


def _row_dict(row: Any) -> dict[str, Any]:
    """Row as a dict that keeps every column: a repeated name gets a _2, _3 suffix."""
    out: dict[str, Any] = {}
    for key, value in row.items():
        name, n = key, 1
        while name in out:
            n += 1
            name = f"{key}_{n}"
        out[name] = value
    return out


@dataclass
class PostgresClient:
    """asyncpg-backed database client with optional read-only enforcement.

    Pass this as ``db_client`` to ``database_query.server.create_server()``.
    The server calls ``fetch_bounded(sql, max_rows)`` for caller SQL and
    ``fetch(schema_query)`` for schema introspection. Give either ``pool`` (owned
    by the caller) or ``dsn`` (the client opens and closes its own pool).
    """

    pool: Any = None
    read_only: bool = True
    dsn: str | None = field(default=None, repr=False)
    max_pool_size: int = 5
    statement_timeout_ms: int = 5_000
    max_result_bytes: int = 1_000_000
    _owned_pool: bool = field(default=False, init=False, repr=False)
    _users: int = field(default=0, init=False, repr=False)
    _open_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        for name in ("statement_timeout_ms", "max_result_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")

    async def open(self) -> None:
        """Create the pool from ``dsn`` on first use; later calls share it.

        A user is counted only once the pool exists, so a failed open needs no close.
        """
        async with self._open_lock:
            if self.pool is None and self.dsn:
                import asyncpg

                self.pool = await asyncpg.create_pool(
                    dsn=self.dsn,
                    min_size=1,
                    max_size=self.max_pool_size,
                    server_settings={"statement_timeout": str(self.statement_timeout_ms)},
                    command_timeout=self.statement_timeout_ms / 1000 + 5,
                )
                self._owned_pool = True
            self._users += 1

    async def close(self) -> None:
        """Close an owned pool once the last user that opened it is done."""
        self._users = max(0, self._users - 1)
        if self._users == 0 and self._owned_pool and self.pool is not None:
            pool, self.pool, self._owned_pool = self.pool, None, False
            await pool.close()

    def _require_pool(self) -> Any:
        if self.pool is None:
            raise RuntimeError("PostgresClient has no pool; call open() or pass pool=")
        return self.pool

    async def fetch_bounded(self, sql: str, max_rows: int) -> tuple[list[dict[str, Any]], bool]:
        """Run one read-only statement and return at most ``max_rows`` rows.

        Always validated as a single plain read, whatever ``read_only`` says. The
        rows come one at a time from a server-side cursor inside a READ ONLY
        transaction with ``statement_timeout`` set, and reading stops after
        ``max_rows`` rows or once the rows read pass ``max_result_bytes``, so a large
        result is never fetched in full. The second item is True when reading
        stopped at either limit (at the byte limit no further row is read, so it
        can be True when no rows were left).
        """
        if max_rows < 1:
            raise ValueError("max_rows must be at least 1")
        validate_single_read(sql)
        rows: list[dict[str, Any]] = []
        size = 0
        async with self._require_pool().acquire() as conn:
            async with conn.transaction(readonly=True):
                await conn.execute(
                    f"SET LOCAL statement_timeout = {int(self.statement_timeout_ms)}"
                )
                cursor = await conn.cursor(sql)
                while size < self.max_result_bytes:
                    row = await cursor.fetchrow()
                    if row is None:
                        return rows, False
                    if len(rows) == max_rows:
                        return rows, True
                    rows.append(_row_dict(row))
                    size += _row_size(row)
        # Byte budget reached: stop without reading another row.
        return rows, True

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        """Execute sql and return rows as list[dict]. Validates read-only if enabled."""
        if self.read_only:
            validate_read_only(sql)

        async with self._require_pool().acquire() as conn:
            rows = await conn.fetch(sql, *args)
            return [dict(row) for row in rows]

    async def execute(self, sql: str, *args: Any) -> str:
        """Execute a non-returning statement (write operations must be explicitly unlocked)."""
        if self.read_only:
            raise PermissionError("Read-only mode: execute() is disabled. Set read_only=False.")
        async with self._require_pool().acquire() as conn:
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
        async with self._require_pool().acquire() as conn:
            rows = await conn.fetch(sql, query_vector, top_k, *params)
            return [dict(row) for row in rows]
