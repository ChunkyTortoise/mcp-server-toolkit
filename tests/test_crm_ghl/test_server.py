"""Tests for CRM GoHighLevel MCP server."""

import pytest

from mcp_toolkit.framework.testing import MCPTestClient
from mcp_toolkit.servers.crm_ghl.field_mapper import GHLField, GHLFieldMapper
from mcp_toolkit.servers.crm_ghl.server import MockGHLClient, configure
from mcp_toolkit.servers.crm_ghl.server import mcp as crm_mcp
from tests.conftest import grant_scopes


@pytest.fixture(autouse=True)
def _auth_context():
    """crm_ghl tools are ``@requires_scope("crm:read")`` / ``"crm:write"``. The
    SDK bearer-auth middleware supplies these from the request's verified token
    in production; under stdio they are absent and tools hard-reject
    (ADR-0008). Grant both scopes via the real SDK auth contextvar so these
    logic tests run; scope enforcement is proved in test_auth_wiring.py.
    """
    with grant_scopes("crm:read", "crm:write"):
        yield


@pytest.fixture
def client():
    configure(client=MockGHLClient())
    return MCPTestClient(crm_mcp)


class TestSearchContacts:
    async def test_search_no_results(self, client):
        result = await client.call_tool("search_contacts", {"query": "nonexistent"})
        assert "No contacts found" in result

    async def test_search_finds_created_contact(self, client):
        await client.call_tool(
            "create_contact",
            {"first_name": "Alice", "last_name": "Smith", "email": "alice@test.com"},
        )
        result = await client.call_tool("search_contacts", {"query": "alice"})
        assert "Alice" in result


class TestCreateContact:
    async def test_create_basic_contact(self, client):
        result = await client.call_tool(
            "create_contact", {"first_name": "John", "last_name": "Doe"}
        )
        assert "Contact created" in result
        assert "John Doe" in result

    async def test_create_with_tags(self, client):
        result = await client.call_tool(
            "create_contact", {"first_name": "Jane", "last_name": "Doe", "tags": "Hot-Lead, Buyer"}
        )
        assert "Contact created" in result

    async def test_create_returns_id(self, client):
        result = await client.call_tool(
            "create_contact", {"first_name": "Bob", "last_name": "Builder"}
        )
        assert "contact_" in result


class TestPipelineSummary:
    async def test_get_default_pipeline(self, client):
        result = await client.call_tool("get_pipeline_summary", {})
        assert "Pipeline" in result
        assert "Total pipeline value" in result

    async def test_pipeline_shows_stages(self, client):
        result = await client.call_tool("get_pipeline_summary", {})
        assert "New" in result
        assert "Qualified" in result


class TestCreateOpportunity:
    async def test_create_opportunity(self, client):
        result = await client.call_tool(
            "create_opportunity", {"contact_id": "contact_1", "name": "Big Deal", "value": 50000}
        )
        assert "Opportunity created" in result
        assert "Big Deal" in result
        assert "50,000" in result


class TestFieldMapper:
    def test_register_and_resolve(self):
        mapper = GHLFieldMapper()
        mapper.register_field(
            GHLField(id="cf_1", name="Lead Source", field_key="lead_source"),
            aliases=["source", "how they found us"],
        )
        field = mapper.resolve("lead source")
        assert field is not None
        assert field.id == "cf_1"

    def test_resolve_alias(self):
        mapper = GHLFieldMapper()
        mapper.register_field(
            GHLField(id="cf_1", name="Lead Source", field_key="lead_source"), aliases=["source"]
        )
        field = mapper.resolve("source")
        assert field is not None

    def test_resolve_unknown(self):
        mapper = GHLFieldMapper()
        assert mapper.resolve("nonexistent") is None

    def test_resolve_dict(self):
        mapper = GHLFieldMapper()
        mapper.register_field(
            GHLField(id="cf_1", name="Lead Source", field_key="lead_source"),
        )
        result = mapper.resolve_dict({"lead source": "Google", "unknown_field": "val"})
        assert result.get("lead_source") == "Google"
        assert result.get("unknown_field") == "val"

    def test_list_fields(self):
        mapper = GHLFieldMapper()
        mapper.register_field(GHLField(id="cf_1", name="A", field_key="a"))
        mapper.register_field(GHLField(id="cf_2", name="B", field_key="b"))
        assert mapper.field_count == 2
        assert len(mapper.list_fields()) == 2


class TestToolListing:
    async def test_has_expected_tools(self, client):
        tools = await client.list_tools()
        names = {t["name"] for t in tools}
        assert "search_contacts" in names
        assert "create_contact" in names
        assert "get_pipeline_summary" in names
        assert "create_opportunity" in names


class TestAuthGateStillEnforced:
    """Guards against the autouse auth fixture silently masking a regression
    where ``@requires_scope`` is removed from a tool."""

    async def test_search_contacts_rejects_without_auth_context(self, client):
        from mcp.server.auth.middleware.auth_context import auth_context_var

        handle = auth_context_var.set(None)
        try:
            result = await client.call_tool("search_contacts", {"query": "anyone"})
        finally:
            auth_context_var.reset(handle)
        assert "Unauthorized" in result

    async def test_write_tool_rejects_when_only_read_scope(self, client):
        """A read-scoped caller must not reach a ``crm:write`` tool."""
        with grant_scopes("crm:read"):
            result = await client.call_tool(
                "create_contact", {"first_name": "No", "last_name": "Access"}
            )
        assert "Forbidden" in result
