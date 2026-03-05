"""Tests for database query MCP server end-to-end."""

import pytest

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
