"""Refusal errors raised by the toolkit guards.

Each subclasses the SDK's ``ToolError``, so MCPServer reports it to the client as
a tool result with ``isError`` true instead of a successful result whose text
happens to start with "Error". Messages are short and colon separated, and they
never echo the caller's scopes, token, arguments or raw exception text.
"""

from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError


class Unauthorized(ToolError):
    """The credential is missing, malformed, expired or otherwise invalid."""


class Forbidden(ToolError):
    """The credential is valid but lacks the scope the tool requires."""


class RateLimited(ToolError):
    """The caller exceeded the tool's rate limit."""
