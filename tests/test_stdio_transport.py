"""The public basic-server example must work through an SDK stdio client.

This catches a broken executable example, missing tool registration, or a wrong
tool result across a real child-process boundary. No hosted service is used.
"""

import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_basic_server_stdio_round_trip():
    root = Path(__file__).resolve().parents[1]
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(root / "examples" / "basic_server.py")],
        cwd=str(root),
        env={"PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    with anyio.fail_after(15):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {tool.name for tool in (await session.list_tools()).tools}
                assert {"add", "greet"} <= names
                result = await session.call_tool("add", {"a": 2, "b": 3})
                assert not result.isError
                assert result.content
                assert result.content[0].type == "text"
                assert float(result.content[0].text) == 5
