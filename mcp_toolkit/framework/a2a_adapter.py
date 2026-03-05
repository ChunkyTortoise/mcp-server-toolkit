"""A2A (Agent-to-Agent) protocol compatibility layer for MCP servers.

Allows MCP servers to expose themselves as A2A-compatible agents for
discovery and interoperability in multi-vendor agent ecosystems.

This is an optional adapter -- MCP servers work without it.
Enable when A2A interop is needed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp_toolkit.framework.base_server import EnhancedMCP


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "capabilities": {
                "streaming": True,
                "pushNotifications": False,
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

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.task_id,
            "status": {"state": self.status},
        }
        if self.message:
            d["status"]["message"] = {"role": "agent", "parts": [{"text": self.message}]}
        if self.result:
            d["result"] = self.result
        return d


class A2AAdapter:
    """Wraps an EnhancedMCP server to expose A2A-compatible endpoints.

    Usage:
        from mcp_toolkit import EnhancedMCP
        from mcp_toolkit.framework.a2a_adapter import A2AAdapter

        mcp = EnhancedMCP("my-server")
        adapter = A2AAdapter(mcp, base_url="https://my-server.example.com")

        # Get agent card for /.well-known/agent.json
        card = adapter.get_agent_card()

        # Execute a task via A2A protocol
        result = await adapter.handle_task("task-123", "query_database", {"question": "..."})
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

    async def build_agent_card(self) -> A2AAgentCard:
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
        )

    async def get_agent_card(self) -> dict[str, Any]:
        """Return the /.well-known/agent.json response."""
        card = await self.build_agent_card()
        return card.to_dict()

    async def handle_task(
        self,
        task_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> A2ATaskStatus:
        """Handle an A2A task by routing to the appropriate MCP tool.

        Maps A2A task submission to MCP tool invocation.
        """
        self._tasks[task_id] = A2ATaskStatus(task_id=task_id, status="working")

        try:
            result = await self._server.call_tool(tool_name, arguments)
            # Extract text from MCP result
            content = result
            if isinstance(result, tuple) and len(result) >= 1:
                content = result[0]
            text = ""
            if isinstance(content, list) and content and hasattr(content[0], "text"):
                text = content[0].text
            elif isinstance(content, str):
                text = content

            status = A2ATaskStatus(
                task_id=task_id,
                status="completed",
                message=text,
                result={"output": text},
            )
        except Exception as e:
            status = A2ATaskStatus(
                task_id=task_id,
                status="failed",
                message=str(e),
            )

        self._tasks[task_id] = status
        return status

    def get_task_status(self, task_id: str) -> A2ATaskStatus | None:
        """Get the status of a previously submitted task."""
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[A2ATaskStatus]:
        """List all tracked tasks."""
        return list(self._tasks.values())
