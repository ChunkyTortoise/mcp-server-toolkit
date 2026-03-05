"""Email MCP Server — Send, search, and draft emails via SMTP/IMAP."""

from mcp_toolkit.servers.email.server import mcp as email_server
from mcp_toolkit.servers.email.template_engine import TemplateEngine

__all__ = ["email_server", "TemplateEngine"]
