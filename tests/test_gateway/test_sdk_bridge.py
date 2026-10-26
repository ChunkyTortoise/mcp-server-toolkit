"""Contract for the SDK internals the gateway depends on.

If an `mcp` upgrade breaks one of these, fix mcp_toolkit/gateway/sdk_bridge.py
and nothing else. Every check names the attribute the toolkit actually uses.
"""

import ast
import inspect
import subprocess
import sys
from pathlib import Path

from mcp_toolkit.gateway import sdk_bridge

PACKAGE = Path(__file__).resolve().parents[2] / "mcp_toolkit"
INTERNAL_PREFIXES = (
    "mcp.server.auth.middleware",
    "mcp.server.auth.provider",
    "mcp.server.auth.settings",
    "mcp.server.lowlevel",
    "mcp.server.transport_security",
)


def test_access_token_accepts_the_fields_the_verifier_sets():
    token = sdk_bridge.AccessToken(
        token="t",
        client_id="c",
        scopes=["orders:read"],
        expires_at=1,
        resource="http://127.0.0.1:8000/mcp",
        subject="s",
        claims={"iss": "http://127.0.0.1:9000"},
    )
    assert (token.subject, token.client_id, token.scopes) == ("s", "c", ["orders:read"])


def test_token_verifier_is_subclassable_with_async_verify_token():
    assert inspect.iscoroutinefunction(sdk_bridge.TokenVerifier.verify_token)

    class Verifier(sdk_bridge.TokenVerifier):
        async def verify_token(self, token):
            return None

    Verifier()


def test_authenticated_user_carries_the_access_token():
    token = sdk_bridge.AccessToken(token="t", client_id="c", scopes=[])
    assert sdk_bridge.AuthenticatedUser(token).access_token is token


async def test_auth_context_middleware_sets_the_token_http_auth_reads():
    from mcp.server.auth.middleware.auth_context import AuthContextMiddleware

    from mcp_toolkit.framework.http_auth import get_request_access_token

    seen = []

    async def app(scope, receive, send):
        seen.append(get_request_access_token())

    token = sdk_bridge.AccessToken(token="t", client_id="per-request", scopes=["orders:read"])
    scope = {"type": "http", "user": sdk_bridge.AuthenticatedUser(token)}
    await AuthContextMiddleware(app)(scope, None, None)
    assert seen == [token]
    assert get_request_access_token() is None


def test_get_access_token_is_none_outside_a_request():
    assert sdk_bridge.get_access_token() is None


def test_auth_settings_accepts_the_gateway_fields():
    settings = sdk_bridge.AuthSettings(
        issuer_url="http://127.0.0.1:9000",
        resource_server_url="http://127.0.0.1:8000/mcp",
        required_scopes=["orders:read"],
        validate_token_resource=True,
    )
    assert settings.required_scopes == ["orders:read"]
    assert settings.validate_token_resource is True


def _imported_names(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
            yield from (f"{node.module}.{alias.name}" for alias in node.names)


def _is_internal(name):
    return any(name == prefix or name.startswith(prefix + ".") for prefix in INTERNAL_PREFIXES)


def test_guard_catches_every_import_form():
    sources = [
        "import mcp.server.auth.provider",
        "from mcp.server.auth import provider",
        "from mcp.server import lowlevel",
        "from mcp.server.lowlevel.server import request_ctx",
    ]
    for source in sources:
        assert any(_is_internal(name) for name in _imported_names(ast.parse(source))), source
    assert not any(
        _is_internal(n) for n in _imported_names(ast.parse("from mcp.types import Tool"))
    )


def test_no_other_module_imports_sdk_internals():
    root = PACKAGE.parent
    offenders = []
    for folder in ("mcp_toolkit", "examples", "scripts"):
        for path in (root / folder).rglob("*.py"):
            if path.name == "sdk_bridge.py":
                continue
            for name in _imported_names(ast.parse(path.read_text())):
                if _is_internal(name):
                    offenders.append(f"{path.relative_to(root)}: {name}")
    assert offenders == []


def test_framework_imports_cleanly_before_the_gateway():
    """framework.http_auth imports gateway.sdk_bridge; gateway/__init__ must stay lazy."""
    for first in ("mcp_toolkit.framework.http_auth", "mcp_toolkit.gateway.sdk_bridge"):
        result = subprocess.run(
            [sys.executable, "-c", f"import {first}; from mcp_toolkit.gateway import main"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr


def test_transport_security_settings_accepts_the_gateway_fields():
    settings = sdk_bridge.TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["app.example:8000"],
        allowed_origins=["https://app.example"],
    )
    assert settings.enable_dns_rebinding_protection is True
    assert settings.allowed_hosts == ["app.example:8000"]
    assert settings.allowed_origins == ["https://app.example"]
