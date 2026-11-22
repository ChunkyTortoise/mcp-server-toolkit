"""Database Query MCP server: read-only SQL, with optional natural language to SQL."""

from mcp_toolkit.servers.database_query.schema_inspector import SchemaInspector
from mcp_toolkit.servers.database_query.server import DatabaseServerSettings, create_server
from mcp_toolkit.servers.database_query.sql_generator import SQLGenerator

__all__ = ["DatabaseServerSettings", "SQLGenerator", "SchemaInspector", "create_server"]
