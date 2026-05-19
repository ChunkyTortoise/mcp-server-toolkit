"""A2A (Agent-to-Agent) protocol compatibility layer for MCP servers.

Allows MCP servers to expose themselves as A2A-compatible agents for
discovery and interoperability in multi-vendor agent ecosystems.

This is an optional adapter -- MCP servers work without it.
Enable when A2A interop is needed.

Streaming: yields Server-Sent Events (SSE) via `stream_task()`.
Push notifications: POSTs status updates to a webhook URL after each state change.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mcp.types import TextContent

if TYPE_CHECKING:
    from mcp_toolkit.framework.base_server import EnhancedMCP

logger = logging.getLogger(__name__)


@dataclass
class A2AAgentCard:
    """Agent card descriptor per A2A spec (/.well-known/agent.json)."""

    name: str
    description: str
    url: str
    version: str = "1.0.0"
    capabilities: list[str] = field(default_factory=list)
    skills: list[dict[str, Any]] = field(default_factory=list)
    authentication: dict[str, Any] = field(default_factory=lambda: {"schemes": ["bearer"]})
    supports_push: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "capabilities": {
                "streaming": True,
                "pushNotifications": self.supports_push,
                "stateTransitionHistory": True,
            },
            "skills": self.skills,
            "authentication": self.authentication,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class A2ATaskStatus:
    """Status of an A2A task."""

    task_id: str
    status: str  # "submitted", "working", "completed", "failed", "canceled"
    message: str = ""
    result: dict[str, Any] | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.task_id,
            "status": {"state": self.status, "timestamp": self.timestamp},
        }
        if self.message:
            d["status"]["message"] = {"role": "agent", "parts": [{"text": self.message}]}
        if self.result:
            d["result"] = self.result
        return d

    def to_sse(self) -> str:
        """Format as a Server-Sent Event string."""
        return f"data: {json.dumps(self.to_dict())}\n\n"


class A2AAdapter:
    """Wraps an EnhancedMCP server to expose A2A-compatible endpoints.

    Supports:
    - SSE streaming via ``stream_task()``
    - Push notifications via webhook URL (requires httpx)
    - Agent card derived from live MCP tool schemas

    Usage:
        from mcp_toolkit import EnhancedMCP
        from mcp_toolkit.framework.a2a_adapter import A2AAdapter

        mcp = EnhancedMCP("my-server")
        adapter = A2AAdapter(mcp, base_url="https://my-server.example.com")

        # Get agent card for /.well-known/agent.json
        card = await adapter.get_agent_card()

        # Stream task updates as SSE
        async for sse_chunk in adapter.stream_task("task-123", "my_tool", {"arg": "val"}):
            print(sse_chunk, end="")

        # Execute without streaming (returns final status)
        result = await adapter.handle_task("task-123", "my_tool", {"arg": "val"},
                                           webhook_url="https://caller.example.com/webhook")
    """

    def __init__(
        self,
        mcp_server: EnhancedMCP,
        base_url: str = "",
        description: str = "",
    ) -> None:
        self._server = mcp_server
        self._base_url = base_url or f"https://{mcp_server.name}.example.com"
        self._description = description or f"MCP server: {mcp_server.name}"
        self._tasks: dict[str, A2ATaskStatus] = {}

    async def build_agent_card(self, webhook_endpoint: str = "") -> A2AAgentCard:
        """Build A2A agent card from MCP server tool metadata."""
        tools = await self._server.list_tools()
        skills = [
            {
                "id": tool.name,
                "name": tool.name,
                "description": tool.description or "",
                "inputModes": ["text"],
                "outputModes": ["text"],
            }
            for tool in tools
        ]
        return A2AAgentCard(
            name=self._server.name,
            description=self._description,
            url=self._base_url,
            skills=skills,
            supports_push=bool(webhook_endpoint),
        )

    async def get_agent_card(self, webhook_endpoint: str = "") -> dict[str, Any]:
        """Return the /.well-known/agent.json response."""
        card = await self.build_agent_card(webhook_endpoint=webhook_endpoint)
        return card.to_dict()

    async def stream_task(
        self,
        task_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> AsyncIterator[str]:
        """Execute an A2A task and yield SSE events for each state transition.

        Yields ``data: {...}\\n\\n`` strings suitable for an HTTP SSE response.
        State sequence: submitted → working → completed | failed
        """
        submitted = A2ATaskStatus(task_id=task_id, status="submitted")
        self._tasks[task_id] = submitted
        yield submitted.to_sse()

        working = A2ATaskStatus(task_id=task_id, status="working", message="Executing tool…")
        self._tasks[task_id] = working
        yield working.to_sse()

        # Yield control so consumers receive the "working" event before the tool runs.
        await asyncio.sleep(0)

        try:
            result_text = await self._invoke_tool(tool_name, arguments)
            final = A2ATaskStatus(
                task_id=task_id,
                status="completed",
                message=result_text,
                result={"output": result_text},
            )
        except Exception as exc:
            # Expected, handled failure — returned to the caller as a
            # "failed" A2ATaskStatus. Log at WARNING (no stack trace) so a
            # correctly-handled task failure does not look like a crash.
            logger.warning("A2A task %s failed: %s", task_id, exc)
            final = A2ATaskStatus(
                task_id=task_id,
                status="failed",
                message=str(exc),
            )

        self._tasks[task_id] = final
        yield final.to_sse()
        yield "data: [DONE]\n\n"

    async def handle_task(
        self,
        task_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        webhook_url: str = "",
    ) -> A2ATaskStatus:
        """Handle an A2A task by routing to the appropriate MCP tool.

        If ``webhook_url`` is provided, POSTs each status update to it.
        Returns the final ``A2ATaskStatus``.
        """
        submitted = A2ATaskStatus(task_id=task_id, status="submitted")
        self._tasks[task_id] = submitted
        await self._notify(submitted, webhook_url)

        working = A2ATaskStatus(task_id=task_id, status="working", message="Executing tool…")
        self._tasks[task_id] = working
        await self._notify(working, webhook_url)

        try:
            result_text = await self._invoke_tool(tool_name, arguments)
            status = A2ATaskStatus(
                task_id=task_id,
                status="completed",
                message=result_text,
                result={"output": result_text},
            )
        except Exception as exc:
            # Expected, handled failure — returned to the caller as a
            # "failed" A2ATaskStatus. Log at WARNING (no stack trace) so a
            # correctly-handled task failure does not look like a crash.
            logger.warning("A2A task %s failed: %s", task_id, exc)
            status = A2ATaskStatus(
                task_id=task_id,
                status="failed",
                message=str(exc),
            )

        self._tasks[task_id] = status
        await self._notify(status, webhook_url)
        return status

    def get_task_status(self, task_id: str) -> A2ATaskStatus | None:
        """Get the status of a previously submitted task."""
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[A2ATaskStatus]:
        """List all tracked tasks."""
        return list(self._tasks.values())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _invoke_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Call the MCP tool and return its text output."""
        result = await self._server.call_tool(tool_name, arguments)
        content = result
        if isinstance(result, tuple) and len(result) >= 1:
            content = result[0]
        if isinstance(content, list) and content and isinstance(content[0], TextContent):
            return content[0].text
        if isinstance(content, str):
            return content
        return str(content)

    async def _notify(self, status: A2ATaskStatus, webhook_url: str) -> None:
        """POST status update to webhook_url if provided. Fire-and-forget on error."""
        if not webhook_url:
            return
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    webhook_url,
                    json=status.to_dict(),
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
        except Exception as exc:
            logger.warning("A2A push notification to %s failed: %s", webhook_url, exc)
