"""Database Query MCP Server — Natural language to SQL."""

from mcp_toolkit.servers.database_query.schema_inspector import SchemaInspector
from mcp_toolkit.servers.database_query.server import mcp as database_query_server
from mcp_toolkit.servers.database_query.sql_generator import SQLGenerator

__all__ = ["database_query_server", "SchemaInspector", "SQLGenerator"]
