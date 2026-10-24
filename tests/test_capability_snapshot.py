"""Every pre-built server exposes tools and nothing else.

FastMCP advertises empty ``prompts`` and ``resources`` capability flags for every
server, so the snapshot pins the exact capability object and then asserts those
lists are empty over the protocol. Sampling, elicitation and roots are client
capabilities a server would request mid-call; the source scan fails if any
server starts requesting them. A new capability fails this test until the
snapshot, README and THREAT_MODEL.md are updated together.
"""

import ast
import importlib
from pathlib import Path

import anyio
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

SERVERS = [
    "analytics",
    "calendar",
    "crm_ghl",
    "database_query",
    "email",
    "file_processing",
    "gemini_embedding",
    "multi_llm",
    "web_scraping",
]

EXPECTED_CAPABILITIES = {
    "experimental": {},
    "prompts": {"listChanged": False},
    "resources": {"subscribe": False, "listChanged": False},
    "tools": {"listChanged": False},
}

# ServerSession methods that ask the client to sample, elicit or list roots.
CLIENT_REQUEST_METHODS = {"create_message", "elicit", "elicit_form", "elicit_url", "list_roots"}

SERVERS_DIR = Path(__file__).resolve().parents[1] / "mcp_toolkit" / "servers"


def test_server_list_matches_package():
    on_disk = sorted(p.name for p in SERVERS_DIR.iterdir() if (p / "server.py").is_file())
    assert on_disk == sorted(SERVERS)


@pytest.mark.parametrize("name", SERVERS)
async def test_server_exposes_only_tools(name):
    server = importlib.import_module(f"mcp_toolkit.servers.{name}.server").mcp
    with anyio.fail_after(10):
        async with create_connected_server_and_client_session(server._mcp_server) as session:
            init = await session.initialize()
            assert init.capabilities.model_dump(exclude_none=True) == EXPECTED_CAPABILITIES
            assert (await session.list_prompts()).prompts == []
            assert (await session.list_resources()).resources == []
            assert (await session.list_resource_templates()).resourceTemplates == []
            assert (await session.list_tools()).tools


@pytest.mark.parametrize("name", SERVERS)
def test_server_never_requests_client_capabilities(name):
    calls = []
    for path in sorted((SERVERS_DIR / name).rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if isinstance(node, ast.Attribute) and node.attr in CLIENT_REQUEST_METHODS:
                calls.append(f"{path.name}:{node.lineno} {node.attr}")
    assert calls == []
