"""Calendar MCP Server — Booking, scheduling, and availability management."""

from mcp_toolkit.servers.calendar.availability import AvailabilityFinder
from mcp_toolkit.servers.calendar.server import mcp as calendar_server

__all__ = ["calendar_server", "AvailabilityFinder"]
