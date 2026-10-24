"""JWT verification and scope checks for SDK streamable HTTP resource servers."""

from __future__ import annotations

import math
import time

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.lowlevel.server import request_ctx
from starlette.requests import Request

from mcp_toolkit.framework.auth import JWTAuth, _audit, _hash_id
from mcp_toolkit.framework.errors import Forbidden
from mcp_toolkit.framework.telemetry import annotate_call


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

    SDK stateful handler tasks inherit the initialize request's auth context.
    The low-level per-message context carries the current HTTP Request instead.
    Only local calls without an HTTP request use the SDK auth-context fallback.
    """
    context = request_ctx.get(None)
    if context is not None and isinstance(context.request, Request):
        user = context.request.scope.get("user")
        return user.access_token if isinstance(user, AuthenticatedUser) else None
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
