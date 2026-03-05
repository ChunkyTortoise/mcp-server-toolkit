"""Tests for Email MCP server."""

import pytest

from mcp_toolkit.framework.testing import MCPTestClient
from mcp_toolkit.servers.email.server import MockEmailClient, configure
from mcp_toolkit.servers.email.server import mcp as email_mcp
from mcp_toolkit.servers.email.template_engine import EmailTemplate, TemplateEngine


@pytest.fixture
def template_engine():
    engine = TemplateEngine()
    engine.register(
        EmailTemplate(
            name="welcome",
            subject="Welcome {{name}}!",
            body="Hello {{name}}, thanks for joining {{company}}.",
        )
    )
    engine.register(
        EmailTemplate(
            name="invoice",
            subject="Invoice #{{invoice_id}}",
            body="Dear {{name}}, your invoice for ${{amount}} is attached.",
        )
    )
    return engine


@pytest.fixture
def client(template_engine):
    configure(client=MockEmailClient(), template_engine=template_engine)
    return MCPTestClient(email_mcp)


class TestSendEmail:
    async def test_send_basic_email(self, client):
        result = await client.call_tool(
            "send_email", {"to": "user@test.com", "subject": "Hello", "body": "Hi there"}
        )
        assert "Email sent" in result
        assert "user@test.com" in result

    async def test_send_with_cc(self, client):
        result = await client.call_tool(
            "send_email",
            {"to": "a@test.com", "subject": "Test", "body": "Body", "cc": "b@test.com"},
        )
        assert "Email sent" in result


class TestSearchEmails:
    async def test_search_finds_match(self, client):
        result = await client.call_tool("search_emails", {"query": "Welcome"})
        assert "Welcome" in result

    async def test_search_no_results(self, client):
        result = await client.call_tool("search_emails", {"query": "nonexistent_xyz"})
        assert "No emails found" in result

    async def test_search_by_sender(self, client):
        result = await client.call_tool("search_emails", {"query": "billing"})
        assert "Invoice" in result


class TestDraftFromTemplate:
    async def test_draft_welcome(self, client):
        result = await client.call_tool(
            "draft_from_template",
            {
                "template_name": "welcome",
                "to": "user@test.com",
                "variables": '{"name": "Alice", "company": "Acme"}',
            },
        )
        assert "Alice" in result
        assert "Acme" in result

    async def test_draft_missing_variable(self, client):
        result = await client.call_tool(
            "draft_from_template",
            {"template_name": "welcome", "to": "user@test.com", "variables": '{"name": "Alice"}'},
        )
        assert "Missing" in result
        assert "company" in result

    async def test_draft_unknown_template(self, client):
        result = await client.call_tool(
            "draft_from_template",
            {
                "template_name": "nonexistent",
                "to": "user@test.com",
            },
        )
        assert "not found" in result

    async def test_draft_invalid_json(self, client):
        result = await client.call_tool(
            "draft_from_template",
            {"template_name": "welcome", "to": "user@test.com", "variables": "invalid json{"},
        )
        assert "Invalid JSON" in result


class TestListTemplates:
    async def test_lists_templates(self, client):
        result = await client.call_tool("list_templates", {})
        assert "welcome" in result
        assert "invoice" in result


class TestTemplateEngine:
    def test_render(self):
        t = EmailTemplate(name="t", subject="Hi {{name}}", body="Hello {{name}}!")
        subj, body = t.render({"name": "Bob"})
        assert subj == "Hi Bob"
        assert body == "Hello Bob!"

    def test_validate_missing(self):
        t = EmailTemplate(name="t", subject="{{a}}", body="{{b}}")
        missing = t.validate({"a": "val"})
        assert "b" in missing

    def test_extract_variables(self):
        t = EmailTemplate(name="t", subject="{{x}}", body="{{y}} and {{x}}")
        assert sorted(t.variables) == ["x", "y"]


class TestToolListing:
    async def test_has_expected_tools(self, client):
        tools = await client.list_tools()
        names = {t["name"] for t in tools}
        assert "send_email" in names
        assert "search_emails" in names
        assert "draft_from_template" in names
        assert "list_templates" in names
