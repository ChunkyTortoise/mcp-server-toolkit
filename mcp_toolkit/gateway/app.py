"""Stateful streamable HTTP with JWT bearer verification by the MCP SDK.

Use MCP_JWKS_URI for externally issued tokens. MCP_JWT_SECRET and
--print-demo-token are local demo conveniences, not an authorization server.
Use on loopback; public Host/Origin deployment configuration is not supplied here.
"""

from __future__ import annotations

import argparse
import os
import time

from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl

from mcp_toolkit.framework.base_server import EnhancedMCP
from mcp_toolkit.framework.http_auth import JWTTokenVerifier, require_scope
from mcp_toolkit.gateway.sdk_bridge import AuthSettings

# mcp 2 takes transport options at run time, not on the constructor.
HTTP_OPTIONS = {"json_response": True}


def create_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    secret: str | None = None,
    jwks_uri: str | None = None,
    resource_url: str | None = None,
    issuer: str = "http://127.0.0.1:9000",
) -> EnhancedMCP:
    """Build the two-tool example with an endpoint-wide orders:read scope."""
    url_host = f"[{host}]" if ":" in host else host
    resource = resource_url or f"http://{url_host}:{port}/mcp"
    server = EnhancedMCP(
        "orders-http",
        token_verifier=JWTTokenVerifier(
            secret=secret, jwks_uri=jwks_uri, audience=resource, issuer=issuer
        ),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(issuer),
            resource_server_url=AnyHttpUrl(resource),
            required_scopes=["orders:read"],
            # The verifier checks aud itself; the SDK check is a second gate.
            validate_token_resource=True,
        ),
    )

    @server.rate_limited_tool(
        max_calls=100,
        title="Read an example order",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def get_order(order_id: str) -> str:
        """Return a synthetic order status."""
        require_scope("orders:read")
        return f"order {order_id}: shipped"

    @server.rate_limited_tool(
        max_calls=100,
        title="Cancel an example order",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True),
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
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8000"))
    url_host = f"[{host}]" if ":" in host else host
    resource = os.environ.get("MCP_RESOURCE_URL") or f"http://{url_host}:{port}/mcp"
    issuer = os.environ.get("MCP_ISSUER", "http://127.0.0.1:9000")
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
                    "aud": resource,
                    "iss": issuer,
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
    create_server(
        host=host, port=port, secret=secret, jwks_uri=jwks_uri, resource_url=resource, issuer=issuer
    ).run(transport="streamable-http", host=host, port=port, **HTTP_OPTIONS)


if __name__ == "__main__":
    main()
