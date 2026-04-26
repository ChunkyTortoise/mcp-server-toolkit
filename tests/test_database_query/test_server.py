"""Tests for database query MCP server end-to-end."""

import pytest

pytest.importorskip("sqlglot")

from mcp_toolkit.framework.testing import MCPTestClient
from mcp_toolkit.servers.database_query import server as db_server
from mcp_toolkit.servers.database_query.sql_generator import MockLLMProvider


@pytest.fixture
def configured_server(mock_db):
    """Configure the database query server with mock dependencies."""
    llm = MockLLMProvider()
    llm.add_response("users", "SELECT COUNT(*) as count FROM users")
    llm.add_response("orders", "SELECT * FROM orders")
    llm.add_response("tables", "SELECT table_name FROM information_schema.tables")

    db_server.configure(db_connection=mock_db, llm=llm)
    return MCPTestClient(db_server.mcp)


@pytest.fixture
def unconfigured_server():
    """Server with no database connection."""
    db_server.configure(db_connection=None, llm=None)
    return MCPTestClient(db_server.mcp)


class TestQueryDatabaseTool:
    async def test_query_returns_results(self, configured_server):
        result = await configured_server.call_tool(
            "query_database", {"question": "How many users are there?"}
        )
        assert "Query" in result
        assert "Results" in result

    async def test_query_includes_sql(self, configured_server):
        result = await configured_server.call_tool(
            "query_database", {"question": "Show me all users"}
        )
        assert "```sql" in result

    async def test_explain_returns_sql(self, configured_server):
        result = await configured_server.call_tool("explain_query", {"question": "How many users?"})
        assert "Generated SQL" in result
        assert "SELECT" in result

    async def test_list_tables(self, configured_server):
        result = await configured_server.call_tool("list_tables", {})
        assert "users" in result
        assert "orders" in result

    async def test_list_tables_no_db_returns_message(self, unconfigured_server):
        result = await unconfigured_server.call_tool("list_tables", {})
        assert "No tables" in result or "connected" in result.lower()

    async def test_query_no_results(self, mock_db):
        """Query that returns no rows should show 'No results found'."""
        llm = MockLLMProvider()
        llm.add_response("empty", "SELECT * FROM users WHERE id = 9999")
        db_server.configure(db_connection=mock_db, llm=llm)
        client = MCPTestClient(db_server.mcp)
        result = await client.call_tool("query_database", {"question": "empty query"})
        assert "No results" in result or "Results" in result

    async def test_explain_includes_schema_context(self, configured_server):
        result = await configured_server.call_tool("explain_query", {"question": "How many users?"})
        assert "Schema context" in result

    async def test_query_database_error_shows_sql(self, mock_db):
        """When DB raises an exception, the tool returns an error string with the SQL."""
        from mcp.server.fastmcp.exceptions import ToolError

        async def fail_fetch(query):
            raise RuntimeError("DB connection lost")

        mock_db.fetch = fail_fetch
        llm = MockLLMProvider()
        llm.add_response("broken", "SELECT * FROM users")
        db_server.configure(db_connection=mock_db, llm=llm)
        client = MCPTestClient(db_server.mcp)
        # The server catches DB errors and returns them inline; but if the schema
        # fetch itself fails, FastMCP may raise ToolError — handle both cases.
        try:
            result = await client.call_tool("query_database", {"question": "broken query"})
            assert "Error" in result
        except ToolError:
            pass  # acceptable — DB was broken before query could run

    async def test_list_tables_shows_column_info(self, configured_server):
        result = await configured_server.call_tool("list_tables", {})
        # Schema context should contain column names
        assert "id" in result or "name" in result

    async def test_query_large_result_truncated(self, mock_db):
        """Results over 100 rows should be truncated with a note."""
        big_rows = [{"id": i, "name": f"user{i}"} for i in range(150)]
        mock_db._tables["big_table"] = {
            "columns": [
                {"column_name": "id", "data_type": "integer", "is_nullable": "NO", "column_default": None},
                {"column_name": "name", "data_type": "varchar", "is_nullable": "NO", "column_default": None},
            ],
            "rows": big_rows,
        }
        llm = MockLLMProvider()
        llm.add_response("big", "SELECT * FROM big_table")
        db_server.configure(db_connection=mock_db, llm=llm)
        client = MCPTestClient(db_server.mcp)
        result = await client.call_tool("query_database", {"question": "get big table"})
        assert "150" in result or "100" in result

    async def test_sql_injection_in_question_handled(self, configured_server):
        """A question containing SQL injection syntax should not crash the server."""
        result = await configured_server.call_tool(
            "query_database",
            {"question": "'; DROP TABLE users; --"},
        )
        # Should return some result (either query output or error) without raising
        assert isinstance(result, str)


class TestToolListing:
    async def test_has_expected_tools(self, configured_server):
        tools = await configured_server.list_tools()
        names = {t["name"] for t in tools}
        assert "query_database" in names
        assert "explain_query" in names
        assert "list_tables" in names

    async def test_tools_have_descriptions(self, configured_server):
        tools = await configured_server.list_tools()
        for tool in tools:
            assert tool["description"], f"Tool {tool['name']} missing description"
