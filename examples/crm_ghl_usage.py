"""Working example: CRM GoHighLevel server.

Demonstrates contact management, pipeline summaries, and opportunity
tracking using the MockGHLClient (no API credentials needed).
"""

import asyncio

from mcp_toolkit.framework.testing import MCPTestClient
from mcp_toolkit.servers.crm_ghl.server import mcp


async def main() -> None:
    client = MCPTestClient(mcp)

    # List available tools
    tools = await client.list_tools()
    print("CRM GHL tools:")
    for tool in tools:
        print(f"  - {tool['name']}: {tool.get('description', '')[:60]}")

    # Create a contact
    print("\n--- create_contact ---")
    result = await client.call_tool(
        "create_contact",
        {
            "first_name": "Jane",
            "last_name": "Smith",
            "email": "jane@example.com",
            "phone": "+15551234567",
            "tags": "Hot-Lead, Buyer",
        },
    )
    print(result)

    # Search for the contact
    print("\n--- search_contacts ---")
    result = await client.call_tool("search_contacts", {"query": "jane", "limit": 5})
    print(result)

    # Get pipeline summary
    print("\n--- get_pipeline_summary ---")
    result = await client.call_tool("get_pipeline_summary", {"pipeline_id": ""})
    print(result)

    # Create an opportunity
    print("\n--- create_opportunity ---")
    result = await client.call_tool(
        "create_opportunity",
        {
            "contact_id": "contact_1",
            "name": "Website Redesign",
            "value": 5000,
            "stage": "Qualified",
        },
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
