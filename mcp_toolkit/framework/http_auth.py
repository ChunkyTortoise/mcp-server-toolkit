"""JWT verification and scope checks for SDK streamable HTTP resource servers."""

from __future__ import annotations

import ipaddress
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import AnyHttpUrl

from mcp_toolkit.framework.auth import JWTAuth, _audit, _hash_id
from mcp_toolkit.framework.errors import Forbidden
from mcp_toolkit.framework.telemetry import annotate_call
from mcp_toolkit.gateway.sdk_bridge import (
    AccessToken,
    TokenVerifier,
    TransportSecuritySettings,
    get_access_token,
)


class JWTTokenVerifier(TokenVerifier):
    """Adapt JWTAuth to the SDK bearer-token interface for one resource audience.

    JWKS mode validates tokens issued elsewhere. A symmetric secret is supported
    for local demos and tests. The SDK uses subject and issuer to bind sessions.
    """

    def __init__(
        self,
        *,
        audience: str,
        secret: str | None = None,
        jwks_uri: str | None = None,
        issuer: str | None = None,
    ) -> None:
        if not audience:
            raise ValueError("JWTTokenVerifier requires an audience resource URL")
        self._audience = audience
        self._auth = JWTAuth(
            secret=secret, jwks_uri=jwks_uri, audience=audience, issuer=issuer, leeway=0
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        result = await self._auth.authenticate(token)
        if not result.authenticated:
            return None
        payload = result.metadata.get("payload", {})
        expiry = payload.get("exp")
        audience = payload.get("aud")
        audience_matches = audience == self._audience or (
            isinstance(audience, list) and self._audience in audience
        )
        invalid_scope_type = any(
            payload.get(name) is not None and not isinstance(payload[name], (str, list))
            for name in ("scope", "scp", "permissions")
        )
        if (
            isinstance(expiry, bool)
            or not isinstance(expiry, (int, float))
            or (isinstance(expiry, float) and not math.isfinite(expiry))
            or expiry <= time.time()
            or not audience_matches
            or not isinstance(result.client_id, str)
            or not result.client_id
            or any(not isinstance(scope, str) for scope in result.scopes)
            or invalid_scope_type
            or payload.get("sub") == ""
        ):
            _audit("jwt.rejected", client_id=result.client_id, error="invalid_transport_claims")
            return None
        return AccessToken(
            token=token,
            client_id=result.client_id,
            scopes=result.scopes,
            expires_at=int(expiry),
            resource=self._audience,
            subject=payload.get("sub"),
            claims={"iss": payload["iss"]} if "iss" in payload else {},
        )


def get_request_access_token() -> AccessToken | None:
    """Return this HTTP request's verified token, not the session creator's.

    mcp 2.x runs each tool call in the context of the HTTP request that carried
    it, so the SDK auth context holds the current bearer token in both JSON and
    SSE response modes. tests/test_gateway/test_transport_auth.py pins that with
    a session whose later request carries a different token. None off HTTP.
    """
    return get_access_token()


def require_scope(scope: str) -> None:
    """Check a per-tool scope in SDK verified context, inside the tool wrapper.

    Endpoint scopes belong in AuthSettings.required_scopes so the SDK refuses
    them with HTTP 403 before dispatch. This check covers additional tool scopes.
    """
    access = get_request_access_token()
    subject = (access.subject or access.client_id) if access else ""
    annotate_call(**{"mcp.subject": _hash_id(subject) if subject else ""})
    if access is None or scope not in access.scopes:
        _audit(
            "scope.denied",
            client_id=access.client_id if access else None,
            required_scope=scope,
        )
        raise Forbidden(f"Forbidden: scope {scope} required")


class HttpConfigError(ValueError):
    """Invalid HTTP bind or deploy configuration."""


def _validate_http_setting(value: str, name: str) -> None:
    """Validate published URLs without echoing configuration into error text."""
    try:
        parsed = AnyHttpUrl(value)
    except (TypeError, ValueError):
        raise HttpConfigError(f"{name} must be an absolute HTTP(S) URL") from None
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise HttpConfigError(f"{name} must not contain userinfo or a fragment")


@dataclass(frozen=True)
class HttpServerSettings:
    """Validated bind and SDK security settings, with field reassignment refused."""

    host: str
    port: int
    resource_url: str
    issuer: str
    deploy_mode: bool
    allowed_hosts: list[str]
    allowed_origins: list[str]
    transport_security: TransportSecuritySettings
    bind_public: bool = False

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Recheck nested settings before a factory uses this configuration."""
        if not isinstance(self.host, str) or not self.host.strip():
            raise HttpConfigError("MCP_HOST must name a bind address")
        if (
            isinstance(self.port, bool)
            or not isinstance(self.port, int)
            or not 0 <= self.port <= 65535
        ):
            raise HttpConfigError("MCP_PORT must be an integer between 0 and 65535")
        _validate_http_setting(self.issuer, "MCP_ISSUER")
        _validate_http_setting(self.resource_url, "MCP_RESOURCE_URL")
        expected_deploy_mode = not _is_loopback_bind(self.host)
        if self.deploy_mode != expected_deploy_mode:
            raise HttpConfigError("deploy_mode must match the bind address")
        if expected_deploy_mode and self.bind_public is not True:
            raise HttpConfigError("non-loopback bind requires MCP_BIND_PUBLIC=1")
        if (
            not isinstance(self.transport_security, TransportSecuritySettings)
            or not self.transport_security.enable_dns_rebinding_protection
        ):
            raise HttpConfigError("Host/Origin protection must be enabled")
        if expected_deploy_mode:
            if not self.allowed_hosts or any("*" in host for host in self.allowed_hosts):
                raise HttpConfigError("public bind requires an exact MCP_ALLOWED_HOSTS list")
        if self.transport_security.allowed_hosts != self.allowed_hosts:
            raise HttpConfigError("MCP_ALLOWED_HOSTS must match the SDK host list")
        if self.transport_security.allowed_origins != self.allowed_origins:
            raise HttpConfigError("MCP_ALLOWED_ORIGINS must match the SDK origin list")


# Keep the SDK's default loopback aliases and add the actual loopback bind.
_LOOPBACK_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
_LOOPBACK_ORIGINS = [
    "http://127.0.0.1:*",
    "http://localhost:*",
    "http://[::1]:*",
]


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _is_loopback_bind(host: str) -> bool:
    candidate = host.strip().lower()
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    if "%" in candidate:
        candidate = candidate.split("%", 1)[0]
    if candidate == "localhost":
        return True
    try:
        address = ipaddress.ip_address(candidate)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return address.is_loopback
    except ValueError:
        return False


def _normalize_bind_host(host: str) -> str:
    value = host.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1]
        try:
            ipaddress.ip_address(inner.split("%", 1)[0])
        except ValueError:
            return value
        return inner
    return value


def _url_host(host: str) -> str:
    if ":" in host:
        return f"[{host}]"
    return host


def _optional_env(env: Mapping[str, str], name: str) -> str | None:
    raw = env.get(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def resolve_http_server_settings(
    environ: Mapping[str, str] | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
    resource_url: str | None = None,
    issuer: str | None = None,
    allowed_hosts: list[str] | None = None,
    allowed_origins: list[str] | None = None,
    bind_public: bool | None = None,
    hosts_configured: bool | None = None,
    origins_configured: bool | None = None,
) -> HttpServerSettings:
    """Resolve bind, audience, and SDK Host/Origin settings.

    Process environment is read only when ``environ`` is passed. Deploy mode is
    any non-loopback bind. It requires ``MCP_BIND_PUBLIC=1``, ``MCP_ISSUER``,
    ``MCP_RESOURCE_URL``, and an exact ``MCP_ALLOWED_HOSTS`` list. An empty
    origin list rejects every supplied Origin and accepts a missing Origin.
    """
    env: Mapping[str, str] = environ if environ is not None else {}
    if host is None:
        host = env.get("MCP_HOST", "127.0.0.1")
    host = _normalize_bind_host(host)
    if port is None:
        raw_port = env.get("MCP_PORT", "8000")
        try:
            port = int(raw_port)
        except (TypeError, ValueError):
            raise HttpConfigError("MCP_PORT must be an integer") from None
    if bind_public is None:
        bind_public = env.get("MCP_BIND_PUBLIC") == "1"
    if hosts_configured is None:
        hosts_configured = environ is not None and "MCP_ALLOWED_HOSTS" in env
    if origins_configured is None:
        origins_configured = environ is not None and "MCP_ALLOWED_ORIGINS" in env
    if allowed_hosts is None and hosts_configured:
        allowed_hosts = _split_csv(env.get("MCP_ALLOWED_HOSTS", ""))
    if allowed_origins is None and origins_configured:
        allowed_origins = _split_csv(env.get("MCP_ALLOWED_ORIGINS", ""))
    if allowed_hosts is None:
        allowed_hosts = []
    if allowed_origins is None:
        allowed_origins = []
    if resource_url is None and environ is not None:
        resource_url = _optional_env(env, "MCP_RESOURCE_URL")
    if issuer is None and environ is not None:
        issuer = _optional_env(env, "MCP_ISSUER")

    deploy_mode = not _is_loopback_bind(host)
    if deploy_mode and not bind_public:
        raise HttpConfigError("non-loopback bind requires MCP_BIND_PUBLIC=1")
    if deploy_mode:
        missing = [
            name
            for name, value in (("MCP_ISSUER", issuer), ("MCP_RESOURCE_URL", resource_url))
            if not value
        ]
        if missing:
            raise HttpConfigError("deploy mode requires " + " and ".join(missing))
        wildcard = any("*" in item for item in allowed_hosts)
        if not hosts_configured or not allowed_hosts or wildcard:
            raise HttpConfigError("public bind requires an exact MCP_ALLOWED_HOSTS list")

    if not resource_url:
        resource_url = f"http://{_url_host(host)}:{port}/mcp"
    if not issuer:
        issuer = "http://127.0.0.1:9000"

    if deploy_mode:
        security_hosts = list(allowed_hosts)
        security_origins = list(allowed_origins) if origins_configured else []
    else:
        bind_host = _url_host(host.lower())
        default_hosts = list(dict.fromkeys([*_LOOPBACK_HOSTS, f"{bind_host}:*"]))
        default_origins = list(dict.fromkeys([*_LOOPBACK_ORIGINS, f"http://{bind_host}:*"]))
        security_hosts = list(allowed_hosts) if hosts_configured else default_hosts
        security_origins = list(allowed_origins) if origins_configured else default_origins
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=security_hosts,
        allowed_origins=security_origins,
    )

    return HttpServerSettings(
        host=host,
        port=port,
        resource_url=resource_url,
        issuer=issuer,
        deploy_mode=deploy_mode,
        allowed_hosts=list(security_hosts),
        allowed_origins=list(security_origins),
        transport_security=transport_security,
        bind_public=bind_public,
    )
