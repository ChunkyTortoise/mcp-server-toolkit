"""CRM GoHighLevel MCP Server — Contact, opportunity, and pipeline management."""

from mcp_toolkit.servers.crm_ghl.field_mapper import GHLFieldMapper
from mcp_toolkit.servers.crm_ghl.server import mcp as crm_ghl_server

__all__ = ["crm_ghl_server", "GHLFieldMapper"]
