"""OAuth 2.0 and API key authentication patterns for MCP servers."""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Any


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
            return AuthResult(authenticated=False, error="Invalid API key")

        if not record.is_active:
            return AuthResult(authenticated=False, error="API key revoked")

        return AuthResult(
            authenticated=True,
            client_id=record.client_id,
            scopes=record.scopes,
            metadata={"rate_limit": record.rate_limit},
        )

    def check_scope(self, auth_result: AuthResult, required_scope: str) -> bool:
        """Check if an auth result includes the required scope."""
        return auth_result.authenticated and required_scope in auth_result.scopes


class OAuthAuth:
    """OAuth 2.0 token validation.

    Validates JWT bearer tokens. In production, verify against a JWKS endpoint.
    For local use, validates using a shared secret (HMAC).
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
        """Issue a simple token (for testing). Production should use proper JWT."""
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
        """Validate a bearer token."""
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
