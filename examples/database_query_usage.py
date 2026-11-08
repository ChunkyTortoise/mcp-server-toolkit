"""Working example: database_query server built with create_server().

Uses a small in-memory client instead of Postgres so it runs anywhere. With a
real database, pass PostgresClient(dsn=..., read_only=True) instead.
"""

import asyncio
from typing import Any

from mcp_toolkit.framework.testing import MCPTestClient
from mcp_toolkit.servers.database_query import DatabaseServerSettings, create_server

ITEMS = [{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}, {"id": 3, "name": "gamma"}]


class DemoClient:
    """In-memory stand-in with the two methods the server calls."""

    async def fetch(self, query: str) -> list[dict[str, Any]]:
        if "information_schema.tables" in query:
            return [{"table_name": "items", "table_schema": "public"}]
        if "information_schema.columns" in query:
            return [
                {
                    "table_schema": "public",
                    "table_name": "items",
                    "column_name": "id",
                    "data_type": "integer",
                    "is_nullable": "NO",
                    "column_default": None,
                },
                {
                    "table_schema": "public",
                    "table_name": "items",
                    "column_name": "name",
                    "data_type": "text",
                    "is_nullable": "NO",
                    "column_default": None,
                },
            ]
        return []

    async def fetch_bounded(self, sql: str, max_rows: int) -> tuple[list[dict[str, Any]], bool]:
        return ITEMS[:max_rows], len(ITEMS) > max_rows


async def main() -> None:
    server = create_server(DatabaseServerSettings(max_rows=2), DemoClient())
    client = MCPTestClient(server)

    print("Available tools:")
    for tool in await client.list_tools():
        print(f"  - {tool['name']}: {tool.get('description', '')[:60]}")

    print("\n--- list_tables ---")
    print(await client.call_tool("list_tables", {}))

    print("\n--- run_sql (capped at 2 rows) ---")
    print(await client.call_tool("run_sql", {"sql": "SELECT id, name FROM items"}))

    print("\n--- run_sql with a write in a CTE ---")
    result = await client.call_tool_result(
        "run_sql", {"sql": "WITH d AS (DELETE FROM items RETURNING *) SELECT * FROM d"}
    )
    print(f"is_error={result.is_error}: {result.content[0].text}")


if __name__ == "__main__":
    asyncio.run(main())
