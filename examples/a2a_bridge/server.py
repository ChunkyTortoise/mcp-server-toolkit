"""A2A bridge server — exposes an MCP server as an A2A-compatible agent.

Run:
    python examples/a2a_bridge/server.py

Endpoints:
    GET  /.well-known/agent.json  — agent card
    POST /tasks/send              — submit task (returns final status)
    POST /tasks/sendSubscribe     — submit task (streams SSE updates)
    GET  /tasks/{task_id}         — poll task status
"""

from __future__ import annotations

import asyncio
import json
import uuid

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from mcp_toolkit import EnhancedMCP
from mcp_toolkit.framework.a2a_adapter import A2AAdapter

# ---------------------------------------------------------------------------
# Build MCP server with a couple of demo tools
# ---------------------------------------------------------------------------
mcp = EnhancedMCP("demo-bridge-server")


@mcp.tool()
async def echo(message: str) -> str:
    """Echo the message back."""
    return f"Echo: {message}"


@mcp.tool()
async def reverse(text: str) -> str:
    """Reverse the input text."""
    return text[::-1]


@mcp.tool()
async def word_count(text: str) -> str:
    """Count words in the input text."""
    count = len(text.split())
    return f"{count} words"


adapter = A2AAdapter(mcp, base_url="http://localhost:8080", description="Demo A2A bridge server")

# ---------------------------------------------------------------------------
# Starlette routes
# ---------------------------------------------------------------------------


async def agent_card(request: Request) -> JSONResponse:
    webhook = request.query_params.get("webhook_endpoint", "")
    card = await adapter.get_agent_card(webhook_endpoint=webhook)
    return JSONResponse(card)


async def tasks_send(request: Request) -> JSONResponse:
    body = await request.json()
    task_id = body.get("id") or str(uuid.uuid4())
    tool_name = body.get("tool") or "echo"
    arguments = body.get("arguments") or {}
    webhook_url = body.get("webhookUrl") or ""

    status = await adapter.handle_task(task_id, tool_name, arguments, webhook_url=webhook_url)
    return JSONResponse(status.to_dict())


async def tasks_send_subscribe(request: Request) -> StreamingResponse:
    """Stream SSE updates as the task executes."""
    body = await request.json()
    task_id = body.get("id") or str(uuid.uuid4())
    tool_name = body.get("tool") or "echo"
    arguments = body.get("arguments") or {}

    async def event_stream():
        async for chunk in adapter.stream_task(task_id, tool_name, arguments):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def task_status(request: Request) -> Response:
    task_id = request.path_params["task_id"]
    status = adapter.get_task_status(task_id)
    if status is None:
        return JSONResponse({"error": "task not found"}, status_code=404)
    return JSONResponse(status.to_dict())


routes = [
    Route("/.well-known/agent.json", agent_card, methods=["GET"]),
    Route("/tasks/send", tasks_send, methods=["POST"]),
    Route("/tasks/sendSubscribe", tasks_send_subscribe, methods=["POST"]),
    Route("/tasks/{task_id}", task_status, methods=["GET"]),
]

app = Starlette(routes=routes)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
