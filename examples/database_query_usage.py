"""Working example: Database Query server with SQLite.

Demonstrates configuring the database server with a mock connection
and using the tools to query, explain, and list tables.
"""

import asyncio

from mcp_toolkit.framework.testing import MCPTestClient
from mcp_toolkit.servers.database_query.server import mcp, configure


async def main() -> None:
    # Configure with defaults (mock DB connection for demo)
    configure()

    client = MCPTestClient(mcp)

    # List available tools
    tools = await client.list_tools()
    print("Available tools:")
    for tool in tools:
        print(f"  - {tool['name']}: {tool.get('description', '')[:60]}")

    # List tables in the database
    print("\n--- list_tables ---")
    result = await client.call_tool("list_tables", {})
    print(result)

    # Query the database with natural language
    print("\n--- query_database ---")
    result = await client.call_tool(
        "query_database", {"question": "How many users signed up last week?"}
    )
    print(result)

    # Explain a query
    print("\n--- explain_query ---")
    result = await client.call_tool(
        "explain_query", {"question": "Show me top customers by revenue"}
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
