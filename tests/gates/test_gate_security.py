"""Gate 2 — Security: auth module correctness and scope enforcement.

Verifies that JWTAuth rejects forged/expired tokens, APIKeyAuth rejects
revoked keys, and the requires_scope decorator blocks unauthorised callers
before the tool function is ever invoked.
"""

from __future__ import annotations

import pytest

from mcp_toolkit.framework.auth import APIKeyAuth, JWTAuth, requires_scope


def _hs_token(secret: str, scopes: list[str], expired: bool = False) -> str:
    import jwt
    import time

    exp = time.time() + (-120 if expired else 3600)
    return jwt.encode(
        {"sub": "test-client", "scope": " ".join(scopes), "exp": exp},
        secret,
        algorithm="HS256",
    )


class TestJWTSecurityGate:
    SECRET = "a-very-long-secret-key-for-testing-purposes-32plus"

    @pytest.fixture
    def auth(self):
        return JWTAuth(secret=self.SECRET)

    async def test_forged_signature_rejected(self, auth):
        good = _hs_token(self.SECRET, ["read"])
        # tamper with the signature
        parts = good.rsplit(".", 1)
        forged = parts[0] + ".AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        result = await auth.authenticate(forged)
        assert result.authenticated is False

    async def test_expired_token_rejected(self, auth):
        token = _hs_token(self.SECRET, ["read"], expired=True)
        result = await auth.authenticate(token)
        assert result.authenticated is False

    async def test_wrong_algorithm_rejected(self):
        """RS256 token must not be accepted by an HS256-configured validator."""
        auth = JWTAuth(secret=self.SECRET)
        # Manually construct a none-alg token (common attack)
        import base64
        import json

        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "none", "typ": "JWT"}).encode()
        ).rstrip(b"=")
        payload = base64.urlsafe_b64encode(
            json.dumps({"sub": "attacker", "scope": "admin"}).encode()
        ).rstrip(b"=")
        token = f"{header.decode()}.{payload.decode()}."
        result = await auth.authenticate(token)
        assert result.authenticated is False

    async def test_missing_token_returns_error(self, auth):
        result = await auth.authenticate("")
        assert result.authenticated is False

    async def test_scope_gate_blocks_insufficient_scopes(self, auth):
        """Security property: a caller whose verified token lacks the required
        scope cannot reach a privileged tool. The credential is the SDK's
        per-request verified token (contextvar), never a tool argument."""
        from tests.conftest import grant_scopes

        @requires_scope("admin")
        async def privileged_tool() -> str:
            return "executed"

        with grant_scopes("read"):
            result = await privileged_tool()
        assert "executed" not in result
        assert "Forbidden" in result

    async def test_scope_gate_never_executes_body_on_bad_auth(self):
        """Security property: the tool body must not run when auth fails. Here
        no verified token is in context (the stdio / unauthenticated path)."""
        side_effects: list[str] = []

        @requires_scope("read")
        async def leaky_tool() -> str:
            side_effects.append("ran")
            return "secret_data"

        result = await leaky_tool()  # no auth context set
        assert side_effects == [], "Tool body executed despite auth failure"
        assert "Unauthorized" in result


class TestAPIKeySecurityGate:
    @pytest.fixture
    def auth(self):
        a = APIKeyAuth()
        a.register_key("valid-key-abc", "client-1", scopes=["read"])
        return a

    async def test_valid_key_accepted(self, auth):
        result = await auth.authenticate("valid-key-abc")
        assert result.authenticated is True

    async def test_revoked_key_rejected(self, auth):
        auth.revoke_key("valid-key-abc")
        result = await auth.authenticate("valid-key-abc")
        assert result.authenticated is False

    async def test_unknown_key_rejected(self, auth):
        result = await auth.authenticate("not-registered-key")
        assert result.authenticated is False

    async def test_empty_key_rejected(self, auth):
        result = await auth.authenticate("")
        assert result.authenticated is False
