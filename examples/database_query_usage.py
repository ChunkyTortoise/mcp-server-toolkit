"""MCP server using the pre-built Database Query server."""

from mcp_toolkit.servers.database_query.server import mcp, configure

# Connect to your database — replace with your actual connection
# configure(db_connection=my_async_db, dialect="postgres")

# Once configured, these tools are available to agents:
#   - query_database("How many users signed up last week?")
#   - explain_query("Show me top customers by revenue")
#   - list_tables()

if __name__ == "__main__":
    mcp.run()
