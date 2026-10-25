"""The only module that imports MCP SDK internals for the HTTP gateway.

Everything here comes from SDK modules that are not part of its documented
public surface and can move between releases. Keeping them in one place means
an SDK upgrade touches this file and tests/test_gateway/test_sdk_bridge.py only.
"""

from __future__ import annotations

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings

__all__ = [
    "AccessToken",
    "AuthSettings",
    "AuthenticatedUser",
    "TokenVerifier",
    "get_access_token",
]
