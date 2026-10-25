"""Stateful streamable HTTP with JWT bearer verification by the MCP SDK.

Use MCP_JWKS_URI for externally issued tokens. MCP_JWT_SECRET and
--print-demo-token are local demo conveniences, not an authorization server.
A non-loopback bind is deploy mode: it needs MCP_BIND_PUBLIC=1, MCP_ISSUER,
MCP_RESOURCE_URL and an exact MCP_ALLOWED_HOSTS list (see docs/DEPLOYMENT.md).
"""

from __future__ import annotations

import argparse
import os
import time
from typing import Any

from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl

from mcp_toolkit.framework.base_server import EnhancedMCP
from mcp_toolkit.framework.http_auth import (
    HttpConfigError,
    HttpServerSettings,
    JWTTokenVerifier,
    require_scope,
    resolve_http_server_settings,
)
from mcp_toolkit.gateway.sdk_bridge import AuthSettings

# mcp 2 takes transport options at run time, not on the constructor.
HTTP_OPTIONS: dict[str, Any] = {"json_response": True}


def http_options(settings: HttpServerSettings) -> dict[str, Any]:
    """Run-time options for ``run`` or ``streamable_http_app``, including Host/Origin checks.

    Explicit ``transport_security`` replaces the SDK's own loopback-only defaults,
    so every bind gets the allow lists the settings were validated with.
    """
    return {**HTTP_OPTIONS, "transport_security": settings.transport_security}


def create_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    secret: str | None = None,
    jwks_uri: str | None = None,
    resource_url: str | None = None,
    issuer: str | None = None,
    allowed_hosts: list[str] | None = None,
    allowed_origins: list[str] | None = None,
    bind_public: bool = False,
    settings: HttpServerSettings | None = None,
) -> EnhancedMCP:
    """Build the two-tool example with an endpoint-wide orders:read scope.

    Pass ``settings`` from ``resolve_http_server_settings`` to reuse one
    environment parse. Otherwise the keyword arguments are resolved alone and
    process environment variables are not read. Host/Origin protection is a run
    time option in mcp 2.x: pass ``http_options(settings)`` to ``run`` or
    ``streamable_http_app``.
    """
    if settings is None:
        settings = resolve_http_server_settings(
            host=host,
            port=port,
            resource_url=resource_url,
            issuer=issuer,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
            bind_public=bind_public,
            hosts_configured=allowed_hosts is not None,
            origins_configured=allowed_origins is not None,
        )
    settings.validate()
    resource = settings.resource_url
    server = EnhancedMCP(
        "orders-http",
        token_verifier=JWTTokenVerifier(
            secret=secret, jwks_uri=jwks_uri, audience=resource, issuer=settings.issuer
        ),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(settings.issuer),
            resource_server_url=AnyHttpUrl(resource),
            required_scopes=["orders:read"],
            # Config guard, not a second token check: the verifier checks aud and reports
            # resource=audience, so this refuses every token only if audience and
            # resource_server_url drift apart.
            validate_token_resource=True,
        ),
    )

    @server.rate_limited_tool(
        max_calls=100,
        title="Read an example order",
        annotations=ToolAnnotations(read_only_hint=True),
    )
    async def get_order(order_id: str) -> str:
        """Return a synthetic order status."""
        require_scope("orders:read")
        return f"order {order_id}: shipped"

    @server.rate_limited_tool(
        max_calls=100,
        title="Cancel an example order",
        annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True),
    )
    async def cancel_order(order_id: str) -> str:
        """Demonstrate an extra per-tool scope on synthetic data."""
        require_scope("orders:write")
        return f"order {order_id}: cancelled (demo only)"

    return server


def main() -> None:
    parser = argparse.ArgumentParser(prog="mcp-toolkit-gateway", description=__doc__)
    parser.add_argument(
        "--print-demo-token",
        metavar="SCOPES",
        help="print a five-minute local HS256 demo token and exit",
    )
    args = parser.parse_args()
    try:
        import jwt
    except ImportError:
        parser.error("PyJWT is missing; install with: pip install 'mcp-server-toolkit[auth]'")
    try:
        settings = resolve_http_server_settings(os.environ)
    except HttpConfigError as exc:
        parser.error(str(exc))
    secret = os.environ.get("MCP_JWT_SECRET") or None
    jwks_uri = os.environ.get("MCP_JWKS_URI") or None
    if args.print_demo_token is not None:
        if not secret or jwks_uri:
            parser.error("--print-demo-token needs MCP_JWT_SECRET and no MCP_JWKS_URI (demo only)")
        print(
            jwt.encode(
                {
                    "sub": "demo-user",
                    "scope": args.print_demo_token,
                    "aud": settings.resource_url,
                    "iss": settings.issuer,
                    "exp": int(time.time()) + 300,
                },
                secret,
                algorithm="HS256",
            )
        )
        return
    if not secret and not jwks_uri:
        parser.error("set MCP_JWKS_URI, or MCP_JWT_SECRET for a local demo")
    if secret and jwks_uri:
        parser.error("set only one of MCP_JWKS_URI and MCP_JWT_SECRET")
    create_server(settings=settings, secret=secret, jwks_uri=jwks_uri).run(
        transport="streamable-http",
        host=settings.host,
        port=settings.port,
        **http_options(settings),
    )


if __name__ == "__main__":
    main()
