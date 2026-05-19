"""CRM GoHighLevel MCP Server — Contact CRUD, pipeline management, and opportunity tracking."""

from __future__ import annotations

import logging
import os
import secrets
from typing import Any, Protocol

from mcp.server.auth.settings import AuthSettings

from mcp_toolkit.framework.auth import JWTAuth, JWTTokenVerifier, requires_scope
from mcp_toolkit.framework.base_server import EnhancedMCP
from mcp_toolkit.servers.crm_ghl.field_mapper import GHLFieldMapper

logger = logging.getLogger(__name__)

# Auth model — credential is the request's verified Authorization bearer token
# (never a tool argument); stdio (default) has no header channel so
# @requires_scope hard-rejects; HTTP mode (MCP_HTTP_PORT) enforces JWT + scope
# and requires MCP_JWT_SECRET. See ADR-0008 for rationale.
_JWT_SECRET = os.environ.get("MCP_JWT_SECRET")
_jwt_auth = JWTAuth(secret=_JWT_SECRET or secrets.token_urlsafe(32))

mcp = EnhancedMCP(
    "crm-ghl",
    token_verifier=JWTTokenVerifier(_jwt_auth),
    auth=AuthSettings(
        issuer_url="https://example.test",
        resource_server_url="http://localhost:8000",
        required_scopes=["crm:read"],
    ),
)

logger = logging.getLogger(__name__)

_field_mapper = GHLFieldMapper()


class GHLClient(Protocol):
    """Protocol for GoHighLevel API client."""

    async def search_contacts(self, query: str, limit: int, filters: dict | None) -> list[dict]: ...

    async def create_contact(self, **kwargs: Any) -> dict: ...

    async def update_contact(self, contact_id: str, **kwargs: Any) -> dict: ...

    async def get_contact(self, contact_id: str) -> dict: ...

    async def get_pipeline_summary(self, pipeline_id: str | None) -> dict: ...

    async def create_opportunity(self, **kwargs: Any) -> dict: ...


class MockGHLClient:
    """Mock GHL client for testing."""

    def __init__(self) -> None:
        self._contacts: dict[str, dict] = {}
        self._opportunities: list[dict] = []
        self._counter = 0

    async def search_contacts(
        self, query: str, limit: int = 20, filters: dict | None = None
    ) -> list[dict]:
        results = []
        for c in self._contacts.values():
            q = query.lower()
            if q in c.get("firstName", "").lower() or q in c.get("email", "").lower():
                results.append(c)
        return results[:limit]

    async def create_contact(self, **kwargs: Any) -> dict:
        self._counter += 1
        contact = {"id": f"contact_{self._counter}", **kwargs}
        self._contacts[contact["id"]] = contact
        return contact

    async def update_contact(self, contact_id: str, **kwargs: Any) -> dict:
        if contact_id not in self._contacts:
            raise ValueError(f"Contact {contact_id} not found")
        self._contacts[contact_id].update(kwargs)
        return self._contacts[contact_id]

    async def get_contact(self, contact_id: str) -> dict:
        if contact_id not in self._contacts:
            raise ValueError(f"Contact {contact_id} not found")
        return self._contacts[contact_id]

    async def get_pipeline_summary(self, pipeline_id: str | None = None) -> dict:
        return {
            "pipeline_id": pipeline_id or "default",
            "stages": [
                {"name": "New", "count": 5, "value": 25000},
                {"name": "Qualified", "count": 3, "value": 45000},
                {"name": "Proposal", "count": 2, "value": 30000},
                {"name": "Won", "count": 1, "value": 15000},
            ],
            "total_value": 115000,
        }

    async def create_opportunity(self, **kwargs: Any) -> dict:
        self._counter += 1
        opp = {"id": f"opp_{self._counter}", **kwargs}
        self._opportunities.append(opp)
        return opp


_client: GHLClient = MockGHLClient()


def configure(client: GHLClient | None = None, field_mapper: GHLFieldMapper | None = None) -> None:
    """Configure the CRM GHL server with a client and field mapper."""
    global _client, _field_mapper
    if client:
        _client = client
    if field_mapper:
        _field_mapper = field_mapper


def _format_contacts(contacts: list[dict]) -> str:
    if not contacts:
        return "No contacts found."
    lines = []
    for c in contacts:
        name = f"{c.get('firstName', '')} {c.get('lastName', '')}".strip()
        email = c.get("email", "N/A")
        phone = c.get("phone", "N/A")
        tags = ", ".join(c.get("tags", []))
        lines.append(f"- **{name}** | {email} | {phone} | Tags: {tags or 'none'}")
    return f"**Found {len(contacts)} contacts:**\n" + "\n".join(lines)


def _format_pipeline(summary: dict) -> str:
    lines = [f"**Pipeline: {summary.get('pipeline_id', 'default')}**\n"]
    for stage in summary.get("stages", []):
        lines.append(f"| {stage['name']} | {stage['count']} deals | ${stage['value']:,.0f} |")
    lines.append(f"\n**Total pipeline value:** ${summary.get('total_value', 0):,.0f}")
    return "\n".join(lines)


@mcp.tool()
@requires_scope("crm:read")
async def search_contacts(
    query: str,
    limit: int = 20,
) -> str:
    """Search GHL contacts by name, email, phone, or custom fields.

    Args:
        query: Search term (name, email, phone).
        limit: Maximum results to return (default 20, max 100).
    """
    limit = min(limit, 100)
    results = await _client.search_contacts(query, limit=limit, filters=None)
    return _format_contacts(results)


@mcp.tool()
@requires_scope("crm:write")
async def create_contact(
    first_name: str,
    last_name: str,
    email: str = "",
    phone: str = "",
    tags: str = "",
) -> str:
    """Create a new contact in GoHighLevel CRM.

    Args:
        first_name: Contact first name.
        last_name: Contact last name.
        email: Contact email address.
        phone: Contact phone number.
        tags: Comma-separated tags (e.g., "Hot-Lead, Buyer").
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    contact = await _client.create_contact(
        firstName=first_name,
        lastName=last_name,
        email=email,
        phone=phone,
        tags=tag_list,
    )
    return f"Contact created: {contact['id']} ({first_name} {last_name})"


@mcp.tool()
@requires_scope("crm:read")
async def get_pipeline_summary(pipeline_id: str = "") -> str:
    """Get summary of deals/opportunities across pipeline stages.

    Args:
        pipeline_id: Optional pipeline ID. Uses default pipeline if empty.
    """
    summary = await _client.get_pipeline_summary(pipeline_id or None)
    return _format_pipeline(summary)


@mcp.tool()
@requires_scope("crm:write")
async def create_opportunity(
    contact_id: str,
    name: str,
    value: float = 0,
    stage: str = "New",
    pipeline_id: str = "",
) -> str:
    """Create a new opportunity/deal in GoHighLevel.

    Args:
        contact_id: Associated contact ID.
        name: Opportunity name.
        value: Deal value in dollars.
        stage: Pipeline stage name.
        pipeline_id: Pipeline ID (uses default if empty).
    """
    opp = await _client.create_opportunity(
        contact_id=contact_id,
        name=name,
        monetary_value=value,
        stage=stage,
        pipeline_id=pipeline_id or "default",
    )
    return f"Opportunity created: {opp['id']} ({name}, ${value:,.0f})"


def main() -> None:
    """Run the server.

    Default transport is **stdio**; every ``@requires_scope`` tool hard-rejects
    under stdio by design (no ``Authorization`` channel — ADR-0008). Set
    ``MCP_HTTP_PORT`` for streamable-HTTP, where JWT + scope are enforced;
    HTTP mode requires ``MCP_JWT_SECRET`` and refuses to start without it.
    """
    if isinstance(_client, MockGHLClient):
        logger.warning(
            "crm-ghl server running with the in-memory MockGHLClient — it does "
            "NOT connect to GoHighLevel (contacts, pipelines, and opportunities "
            "are fake). No real GHL client ships with the toolkit; inject one "
            "via crm_ghl.server.configure(client=...)."
        )
    http_port = os.environ.get("MCP_HTTP_PORT")
    if http_port:
        if not _JWT_SECRET:
            raise SystemExit(
                "MCP_HTTP_PORT is set but MCP_JWT_SECRET is not. HTTP mode "
                "enforces JWT bearer auth and refuses to start without an "
                "explicit verification secret."
            )
        mcp.settings.port = int(http_port)
        logger.info("Starting crm-ghl over streamable-http on port %s", http_port)
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
