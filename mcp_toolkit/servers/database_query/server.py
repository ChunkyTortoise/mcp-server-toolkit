"""Database Query MCP Server — Natural language to SQL with sqlglot validation."""

from __future__ import annotations

import logging
import os
import secrets
from typing import Any

from mcp.server.auth.settings import AuthSettings

from mcp_toolkit.framework.auth import JWTAuth, JWTTokenVerifier, requires_scope
from mcp_toolkit.framework.base_server import EnhancedMCP
from mcp_toolkit.servers.database_query.schema_inspector import (
    DatabaseSchema,
    SchemaInspector,
)
from mcp_toolkit.servers.database_query.sql_generator import (
    DefaultLLMProvider,
    LLMProvider,
    SQLGenerator,
)

logger = logging.getLogger(__name__)

# Auth model — credential is the request's verified Authorization bearer token
# (never a tool argument); stdio (default) has no header channel so
# @requires_scope hard-rejects; HTTP mode (MCP_HTTP_PORT) enforces JWT + scope
# and requires MCP_JWT_SECRET. Unset MCP_JWT_SECRET -> ephemeral secret so stdio
# import still works (nothing validates against it). See ADR-0008 for rationale.
_JWT_SECRET = os.environ.get("MCP_JWT_SECRET")
_jwt_auth = JWTAuth(secret=_JWT_SECRET or secrets.token_urlsafe(32))

mcp = EnhancedMCP(
    "database-query",
    token_verifier=JWTTokenVerifier(_jwt_auth),
    auth=AuthSettings(
        issuer_url="https://example.test",
        resource_server_url="http://localhost:8000",
        required_scopes=["db:read"],
    ),
)

_schema_inspector = SchemaInspector()
_sql_generator = SQLGenerator()
_db_connection: Any = None
_schema_cache: DatabaseSchema | None = None


def configure(
    db_connection: Any = None,
    llm: LLMProvider | None = None,
    dialect: str = "postgres",
) -> None:
    """Configure the database query server with a connection and LLM provider."""
    global _db_connection, _sql_generator, _schema_inspector, _schema_cache
    _db_connection = db_connection
    _sql_generator = SQLGenerator(llm=llm or DefaultLLMProvider(), dialect=dialect)
    _schema_inspector = SchemaInspector(db=db_connection)
    _schema_cache = None


async def _get_schema() -> DatabaseSchema:
    global _schema_cache
    if _schema_cache is not None:
        return _schema_cache
    if _db_connection is not None:
        _schema_cache = await _schema_inspector.inspect(_db_connection)
        return _schema_cache
    return DatabaseSchema()


async def _execute_query(sql: str) -> list[dict[str, Any]]:
    """Execute a read-only SQL query."""
    if _db_connection is None:
        raise RuntimeError("No database connection configured")
    return await _db_connection.fetch(sql)


def _format_results(rows: list[dict[str, Any]]) -> str:
    """Format query results as a markdown table."""
    if not rows:
        return "No results found."

    headers = list(rows[0].keys())
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows[:100]:
        values = [str(row.get(h, "")) for h in headers]
        lines.append("| " + " | ".join(values) + " |")

    if len(rows) > 100:
        lines.append(f"\n*Showing first 100 of {len(rows)} results.*")

    return "\n".join(lines)


@mcp.tool()
@requires_scope("db:read")
async def query_database(question: str) -> str:
    """Convert a natural language question to SQL and execute it.

    Args:
        question: Natural language question (e.g., "How many users signed up last week?")

    Returns:
        Formatted query results as a markdown table with the generated SQL.
    """
    schema = await _get_schema()
    sql, is_valid, validated = await _sql_generator.generate_and_validate(question, schema)

    if not is_valid:
        return f"Error generating query: {validated}"

    try:
        results = await _execute_query(validated)
        table = _format_results(results)
        return f"**Query:**\n```sql\n{validated}\n```\n\n**Results:**\n{table}"
    except Exception as e:
        return f"**Query:**\n```sql\n{validated}\n```\n\nError executing query: {e}"


@mcp.tool()
@requires_scope("db:read")
async def explain_query(question: str) -> str:
    """Generate SQL from a natural language question and show the query without executing.

    Args:
        question: Natural language question to convert to SQL.

    Returns:
        The generated SQL query and schema context used.
    """
    schema = await _get_schema()
    sql, is_valid, validated = await _sql_generator.generate_and_validate(question, schema)

    if not is_valid:
        return f"Error: {validated}"

    return f"**Generated SQL:**\n```sql\n{validated}\n```\n\n**Schema context:**\n{schema.to_context()}"


@mcp.tool()
@requires_scope("db:read")
async def list_tables() -> str:
    """List all tables in the connected database with their column information."""
    schema = await _get_schema()
    if not schema.tables:
        return "No tables found. Is the database connected?"
    return schema.to_context()


def main() -> None:
    """Run the server.

    Default transport is **stdio** (Claude Desktop / IDE plugins). Because
    stdio carries no ``Authorization`` header, every ``@requires_scope`` tool
    hard-rejects under it by design (ADR-0008).

    Set ``MCP_HTTP_PORT`` to run streamable-HTTP instead, where the SDK's
    bearer-auth middleware enforces JWT + scope. HTTP mode requires
    ``MCP_JWT_SECRET`` to be set explicitly — it refuses to start otherwise so
    auth can never silently no-op.
    """
    http_port = os.environ.get("MCP_HTTP_PORT")
    if http_port:
        if not _JWT_SECRET:
            raise SystemExit(
                "MCP_HTTP_PORT is set but MCP_JWT_SECRET is not. HTTP mode "
                "enforces JWT bearer auth and refuses to start without an "
                "explicit verification secret."
            )
        mcp.settings.port = int(http_port)
        logger.info("Starting database-query over streamable-http on port %s", http_port)
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
