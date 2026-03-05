"""Email MCP Server — Send, search, and draft emails."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from mcp_toolkit.framework.base_server import EnhancedMCP
from mcp_toolkit.servers.email.template_engine import TemplateEngine

mcp = EnhancedMCP("email")

_template_engine = TemplateEngine()


class EmailClient(Protocol):
    """Protocol for email sending/receiving."""

    async def send(self, to: str, subject: str, body: str, cc: str, bcc: str) -> dict: ...

    async def search(self, query: str, folder: str, limit: int) -> list[dict]: ...


@dataclass
class MockEmailMessage:
    id: str
    to: str
    subject: str
    body: str
    sender: str = "agent@example.com"
    cc: str = ""
    bcc: str = ""
    folder: str = "INBOX"


class MockEmailClient:
    """Mock email client for testing."""

    def __init__(self) -> None:
        self._sent: list[MockEmailMessage] = []
        self._inbox: list[MockEmailMessage] = [
            MockEmailMessage(
                id="msg_1",
                to="user@test.com",
                subject="Welcome",
                body="Welcome aboard!",
                sender="admin@test.com",
            ),
            MockEmailMessage(
                id="msg_2",
                to="user@test.com",
                subject="Invoice #123",
                body="Your invoice is attached.",
                sender="billing@test.com",
            ),
        ]
        self._counter = 0

    async def send(self, to: str, subject: str, body: str, cc: str = "", bcc: str = "") -> dict:
        self._counter += 1
        msg = MockEmailMessage(
            id=f"sent_{self._counter}", to=to, subject=subject, body=body, cc=cc, bcc=bcc
        )
        self._sent.append(msg)
        return {"id": msg.id, "status": "sent"}

    async def search(self, query: str, folder: str = "INBOX", limit: int = 20) -> list[dict]:
        results = []
        q = query.lower()
        for msg in self._inbox:
            if q in msg.subject.lower() or q in msg.body.lower() or q in msg.sender.lower():
                results.append(
                    {
                        "id": msg.id,
                        "subject": msg.subject,
                        "from": msg.sender,
                        "preview": msg.body[:100],
                    }
                )
        return results[:limit]


_client: EmailClient = MockEmailClient()


def configure(
    client: EmailClient | None = None, template_engine: TemplateEngine | None = None
) -> None:
    global _client, _template_engine
    if client:
        _client = client
    if template_engine:
        _template_engine = template_engine


@mcp.tool()
async def send_email(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
) -> str:
    """Send an email.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Email body (plain text or HTML).
        cc: CC recipients (comma-separated).
        bcc: BCC recipients (comma-separated).
    """
    result = await _client.send(to=to, subject=subject, body=body, cc=cc, bcc=bcc)
    return f"Email sent to {to}: {result.get('id', 'unknown')} (status: {result.get('status', 'unknown')})"


@mcp.tool()
async def search_emails(
    query: str,
    folder: str = "INBOX",
    limit: int = 20,
) -> str:
    """Search emails by keyword.

    Args:
        query: Search term (searches subject, body, sender).
        folder: Email folder to search (default INBOX).
        limit: Maximum results (default 20).
    """
    results = await _client.search(query=query, folder=folder, limit=limit)
    if not results:
        return f"No emails found matching '{query}' in {folder}."
    lines = [f"**Found {len(results)} emails:**"]
    for msg in results:
        lines.append(f"- [{msg['id']}] **{msg['subject']}** from {msg['from']}")
    return "\n".join(lines)


@mcp.tool()
async def draft_from_template(
    template_name: str,
    to: str,
    variables: str = "{}",
) -> str:
    """Draft an email from a registered template.

    Args:
        template_name: Name of the registered template.
        to: Recipient email address.
        variables: JSON string of template variables (e.g., '{"name": "John"}').
    """
    try:
        vars_dict = json.loads(variables)
    except json.JSONDecodeError:
        return "Error: Invalid JSON in variables."

    template = _template_engine.get(template_name)
    if not template:
        available = [t.name for t in _template_engine.list_templates()]
        return f"Template '{template_name}' not found. Available: {', '.join(available) or 'none'}"

    missing = template.validate(vars_dict)
    if missing:
        return f"Missing template variables: {', '.join(missing)}"

    subject, body = template.render(vars_dict)
    return f"**Draft email to {to}:**\n\nSubject: {subject}\n\n{body}"


@mcp.tool()
async def list_templates() -> str:
    """List all registered email templates."""
    templates = _template_engine.list_templates()
    if not templates:
        return "No email templates registered."
    lines = ["**Email templates:**"]
    for t in templates:
        vars_str = ", ".join(t.variables) if t.variables else "none"
        lines.append(f"- **{t.name}**: {t.subject} (vars: {vars_str})")
    return "\n".join(lines)
