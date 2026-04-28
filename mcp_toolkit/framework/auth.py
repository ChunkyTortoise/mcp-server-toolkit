"""OAuth 2.1 and API key authentication for MCP servers."""

from __future__ import annotations

import asyncio
import functools
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

audit_logger = logging.getLogger("mcp_toolkit.auth.audit")
logger = logging.getLogger(__name__)


@dataclass
class AuthResult:
    """Result of an authentication check."""

    authenticated: bool
    client_id: str | None = None
    scopes: list[str] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class APIKeyRecord:
    """Stored API key record."""

    key_hash: str
    client_id: str
    scopes: list[str] = field(default_factory=lambda: ["read"])
    rate_limit: int = 100
    is_active: bool = True
    created_at: float = field(default_factory=time.time)


class APIKeyAuth:
    """API key authentication provider.

    Stores hashed API keys in memory. In production, back with a database.
    """

    def __init__(self) -> None:
        self._keys: dict[str, APIKeyRecord] = {}

    @staticmethod
    def hash_key(api_key: str) -> str:
        return hashlib.sha256(api_key.encode()).hexdigest()

    def register_key(
        self,
        api_key: str,
        client_id: str,
        scopes: list[str] | None = None,
        rate_limit: int = 100,
    ) -> APIKeyRecord:
        """Register a new API key."""
        record = APIKeyRecord(
            key_hash=self.hash_key(api_key),
            client_id=client_id,
            scopes=scopes or ["read"],
            rate_limit=rate_limit,
        )
        self._keys[record.key_hash] = record
        return record

    def revoke_key(self, api_key: str) -> bool:
        """Revoke an API key."""
        key_hash = self.hash_key(api_key)
        if key_hash in self._keys:
            self._keys[key_hash].is_active = False
            return True
        return False

    async def authenticate(self, api_key: str) -> AuthResult:
        """Authenticate an API key."""
        if not api_key:
            return AuthResult(authenticated=False, error="Missing API key")

        key_hash = self.hash_key(api_key)
        record = self._keys.get(key_hash)

        if record is None:
            _audit("api_key.rejected", error="invalid_key")
            return AuthResult(authenticated=False, error="Invalid API key")

        if not record.is_active:
            _audit("api_key.rejected", client_id=record.client_id, error="revoked")
            return AuthResult(authenticated=False, error="API key revoked")

        _audit("api_key.accepted", client_id=record.client_id, scopes=record.scopes)
        return AuthResult(
            authenticated=True,
            client_id=record.client_id,
            scopes=record.scopes,
            metadata={"rate_limit": record.rate_limit},
        )

    def check_scope(self, auth_result: AuthResult, required_scope: str) -> bool:
        """Check if an auth result includes the required scope."""
        return auth_result.authenticated and required_scope in auth_result.scopes


class JWTAuth:
    """Production OAuth 2.1 resource-server JWT validator.

    Supports two modes:

    * **HS256** (``secret=``): symmetric HMAC — suitable for single-tenant setups
      or internal services where both sides share a secret.
    * **RS256 / JWKS** (``jwks_uri=``): fetches the public-key set from a
      JWKS endpoint (Auth0, Okta, Keycloak, custom IdP). Keys are cached and
      rotated automatically via ``PyJWT.PyJWKClient``.

    Args:
        secret:     Shared secret for HS256 mode. Mutually exclusive with jwks_uri.
        jwks_uri:   JWKS URL for RS256 mode (e.g. https://myapp.us.auth0.com/.well-known/jwks.json).
        audience:   Expected ``aud`` claim. Omit to skip audience verification.
        issuer:     Expected ``iss`` claim. Omit to skip issuer verification.
        leeway:     Seconds of clock-skew tolerance for ``exp``/``nbf`` (default: 30).
        algorithms: Allowed algorithms. Defaults to [\"HS256\"] or [\"RS256\"] based on mode.
    """

    def __init__(
        self,
        *,
        secret: str | None = None,
        jwks_uri: str | None = None,
        audience: str | list[str] | None = None,
        issuer: str | None = None,
        leeway: int = 30,
        algorithms: list[str] | None = None,
    ) -> None:
        if not secret and not jwks_uri:
            raise ValueError("JWTAuth requires either 'secret' (HS256) or 'jwks_uri' (RS256).")
        if secret and jwks_uri:
            raise ValueError("Provide either 'secret' or 'jwks_uri', not both.")

        self._secret = secret
        self._jwks_uri = jwks_uri
        self._audience = audience
        self._issuer = issuer
        self._leeway = leeway
        self._algorithms = algorithms or (["HS256"] if secret else ["RS256"])
        self._jwks_client: Any | None = None

        if jwks_uri:
            self._init_jwks_client(jwks_uri)

    def _init_jwks_client(self, jwks_uri: str) -> None:
        try:
            import jwt

            self._jwks_client = jwt.PyJWKClient(jwks_uri, cache_keys=True)
            logger.info("JWTAuth JWKS client initialised: %s", jwks_uri)
        except ImportError:
            raise ImportError(
                "PyJWT[cryptography] is required for JWTAuth. "
                "Install with: pip install 'mcp-server-toolkit[auth]'"
            ) from None

    async def authenticate(self, token: str) -> AuthResult:
        """Validate a JWT bearer token and return an AuthResult."""
        if not token:
            return AuthResult(authenticated=False, error="Missing token")
        token = token.removeprefix("Bearer ").strip()

        try:
            import jwt as pyjwt

            decode_kwargs: dict[str, Any] = {
                "algorithms": self._algorithms,
                "leeway": self._leeway,
            }
            if self._audience:
                decode_kwargs["audience"] = self._audience
            if self._issuer:
                decode_kwargs["issuer"] = self._issuer

            if self._jwks_client is not None:
                # RS256: resolve signing key from JWKS (blocks on HTTP in executor)
                signing_key = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self._jwks_client.get_signing_key_from_jwt,
                    token,
                )
                payload = pyjwt.decode(token, signing_key.key, **decode_kwargs)
            else:
                # HS256: symmetric secret
                payload = pyjwt.decode(token, self._secret, **decode_kwargs)

        except Exception as exc:
            error_type = type(exc).__name__
            _audit("jwt.rejected", error=error_type)
            return AuthResult(authenticated=False, error=_jwt_error_message(exc))

        client_id = payload.get("sub") or payload.get("client_id") or payload.get("azp")
        scopes = _extract_scopes(payload)

        _audit("jwt.accepted", client_id=client_id, scopes=scopes)
        return AuthResult(
            authenticated=True,
            client_id=client_id,
            scopes=scopes,
            metadata={"payload": payload},
        )

    def check_scope(self, auth_result: AuthResult, required_scope: str) -> bool:
        return auth_result.authenticated and required_scope in auth_result.scopes


def requires_scope(auth: APIKeyAuth | JWTAuth, scope: str) -> Callable:
    """Decorator that enforces authentication and scope on an MCP tool.

    The wrapped tool must accept a ``token`` kwarg (for JWT) or ``api_key``
    kwarg (for API keys). The decorator validates the credential and returns
    an error string if authentication or scope check fails.

    Usage::

        @mcp.tool()
        @requires_scope(jwt_auth, "db:read")
        async def query_database(sql: str, token: str = "") -> str:
            ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            credential = (
                kwargs.get("token")
                or kwargs.get("api_key")
                or kwargs.get("authorization")
                or ""
            )
            result = await auth.authenticate(credential)
            if not result.authenticated:
                return f"Error: Unauthorized — {result.error}"
            if scope and not auth.check_scope(result, scope):
                return f"Error: Forbidden — scope '{scope}' required, have {result.scopes}"
            return await func(*args, **kwargs)

        return wrapper

    return decorator


class OAuthAuth:
    """HMAC-based token store for **testing only**.

    .. deprecated::
        ``OAuthAuth`` is a test stub — it stores tokens in a plain dict and uses
        HMAC hex as a token format, not real JWTs. Use :class:`JWTAuth` for
        production deployments.
    """

    def __init__(self, secret: str = "", issuer: str = "") -> None:
        self._secret = secret
        self._issuer = issuer
        self._tokens: dict[str, dict[str, Any]] = {}

    def issue_token(
        self,
        client_id: str,
        scopes: list[str] | None = None,
        expires_in: int = 3600,
    ) -> str:
        """Issue a test token. Production should use a real OAuth 2.1 server."""
        payload = {
            "client_id": client_id,
            "scopes": scopes or ["read"],
            "exp": time.time() + expires_in,
            "iss": self._issuer,
        }
        token = hmac.new(
            self._secret.encode(),
            f"{client_id}:{payload['exp']}".encode(),
            hashlib.sha256,
        ).hexdigest()
        self._tokens[token] = payload
        return token

    async def authenticate(self, token: str) -> AuthResult:
        """Validate a test token."""
        if not token:
            return AuthResult(authenticated=False, error="Missing token")

        payload = self._tokens.get(token)
        if payload is None:
            return AuthResult(authenticated=False, error="Invalid token")

        if time.time() > payload.get("exp", 0):
            return AuthResult(authenticated=False, error="Token expired")

        return AuthResult(
            authenticated=True,
            client_id=payload["client_id"],
            scopes=payload.get("scopes", []),
        )

    def check_scope(self, auth_result: AuthResult, required_scope: str) -> bool:
        return auth_result.authenticated and required_scope in auth_result.scopes


# ── helpers ──────────────────────────────────────────────────────────────────


def _extract_scopes(payload: dict[str, Any]) -> list[str]:
    """Extract scopes from a JWT payload, handling common claim variants."""
    raw = payload.get("scope") or payload.get("scp") or payload.get("permissions")
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        return raw.split()
    return []


def _jwt_error_message(exc: Exception) -> str:
    """Map PyJWT exceptions to user-facing error strings."""
    name = type(exc).__name__
    if "Expired" in name:
        return "Token expired"
    if "InvalidSignature" in name:
        return "Invalid token signature"
    if "InvalidAudience" in name:
        return "Invalid token audience"
    if "InvalidIssuer" in name:
        return "Invalid token issuer"
    if "DecodeError" in name or "InvalidToken" in name:
        return "Malformed token"
    return f"Token validation failed: {exc}"


def _audit(event: str, **fields: Any) -> None:
    """Emit a structured audit log entry."""
    audit_logger.info(json.dumps({"event": event, "ts": time.time(), **fields}))
