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


class TestMainWiring:
    def test_main_wires_smtp_client_when_env_set(self, monkeypatch):
        """main() with SMTP_HOST set must configure an SMTPEmailClient."""
        import mcp_toolkit.servers.email.server as email_server
        from mcp_toolkit.servers.email.smtp_client import SMTPEmailClient

        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_USER", "user@example.com")
        monkeypatch.setenv("SMTP_PASS", "secret")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.setenv("IMAP_HOST", "imap.example.com")

        # Patch mcp.run so main() doesn't actually start a server
        monkeypatch.setattr(email_server.mcp, "run", lambda: None)

        email_server.main()

        assert isinstance(email_server._client, SMTPEmailClient)
        assert email_server._client.host == "smtp.example.com"
        assert email_server._client.username == "user@example.com"
        assert email_server._client.imap_host == "imap.example.com"

    def test_main_keeps_mock_client_without_env(self, monkeypatch):
        """main() without SMTP_HOST must leave MockEmailClient in place."""
        import mcp_toolkit.servers.email.server as email_server

        monkeypatch.delenv("SMTP_HOST", raising=False)
        monkeypatch.setattr(email_server.mcp, "run", lambda: None)

        email_server.configure(client=MockEmailClient())  # reset to known mock
        email_server.main()

        assert isinstance(email_server._client, MockEmailClient)
