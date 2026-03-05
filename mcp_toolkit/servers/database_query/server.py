"""Database Query MCP Server — Natural language to SQL with sqlglot validation."""

from __future__ import annotations

from typing import Any

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

mcp = EnhancedMCP("database-query")

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
async def list_tables() -> str:
    """List all tables in the connected database with their column information."""
    schema = await _get_schema()
    if not schema.tables:
        return "No tables found. Is the database connected?"
    return schema.to_context()
