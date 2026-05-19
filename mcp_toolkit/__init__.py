"""MCP Server Toolkit — Production-ready MCP server framework and pre-built servers."""

from mcp_toolkit.framework.auth import (
    APIKeyAuth,
    JWTAuth,
    JWTTokenVerifier,
    OAuthAuth,
    requires_scope,
)
from mcp_toolkit.framework.base_server import EnhancedMCP
from mcp_toolkit.framework.costing import CostTracker
from mcp_toolkit.framework.testing import MCPTestClient

__all__ = [
    "EnhancedMCP",
    "MCPTestClient",
    "APIKeyAuth",
    "JWTAuth",
    "JWTTokenVerifier",
    "OAuthAuth",
    "requires_scope",
    "CostTracker",
]
__version__ = "0.3.0.dev0"
