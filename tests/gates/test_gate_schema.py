"""Gate 1 — Schema: every registered tool exposes a typed, non-empty description.

Validates that all toolkit servers meet the MCP contract for tool discoverability.
A tool that ships without a description is unusable by an LLM.
"""

from __future__ import annotations

import importlib

import pytest

from mcp_toolkit.framework.testing import MCPTestClient

_SERVERS = [
    "mcp_toolkit.servers.web_scraping.server",
    "mcp_toolkit.servers.file_processing.server",
    "mcp_toolkit.servers.analytics.server",
    "mcp_toolkit.servers.email.server",
    "mcp_toolkit.servers.calendar.server",
    "mcp_toolkit.servers.crm_ghl.server",
    "mcp_toolkit.servers.gemini_embedding.server",
    "mcp_toolkit.servers.multi_llm.server",
    # database_query requires sqlglot — imported separately with skip guard
]

_OPTIONAL_SERVERS = [
    "mcp_toolkit.servers.database_query.server",
]


def _try_load(module_path: str):
    """Import a server module and return its `mcp` attribute, or None if deps missing."""
    try:
        mod = importlib.import_module(module_path)
        return getattr(mod, "mcp", None)
    except ImportError:
        return None


@pytest.mark.parametrize("module_path", _SERVERS)
def test_server_importable(module_path: str):
    importlib.import_module(module_path)


@pytest.mark.parametrize("module_path", _OPTIONAL_SERVERS)
def test_optional_server_importable_or_skipped(module_path: str):
    try:
        importlib.import_module(module_path)
    except ImportError as e:
        pytest.skip(f"Optional dependency not installed: {e}")


@pytest.mark.parametrize("module_path", _SERVERS)
def test_server_exposes_mcp(module_path: str):
    mcp = _try_load(module_path)
    assert mcp is not None, f"{module_path} has no 'mcp' attribute"


@pytest.mark.parametrize("module_path", _SERVERS)
async def test_tools_have_descriptions(module_path: str):
    mcp = _try_load(module_path)
    if mcp is None:
        pytest.skip(f"{module_path}: import failed")

    client = MCPTestClient(mcp)
    tools = await client.list_tools()
    assert tools, f"{module_path} registers no tools"

    no_desc = [t["name"] for t in tools if not t.get("description", "").strip()]
    assert not no_desc, f"{module_path}: tools missing descriptions: {no_desc}"


@pytest.mark.parametrize("module_path", _SERVERS)
async def test_tools_have_unique_names(module_path: str):
    mcp = _try_load(module_path)
    if mcp is None:
        pytest.skip(f"{module_path}: import failed")

    client = MCPTestClient(mcp)
    tools = await client.list_tools()
    names = [t["name"] for t in tools]
    assert len(names) == len(set(names)), f"Duplicate tool names in {module_path}: {names}"
