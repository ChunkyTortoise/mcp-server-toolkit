"""Tests for authentication module."""

import time

import jwt
import pytest

from mcp_toolkit.framework.auth import (
    APIKeyAuth,
    JWTAuth,
    JWTTokenVerifier,
    OAuthAuth,
    requires_scope,
)


class TestAPIKeyAuth:
    async def test_register_and_authenticate(self, api_key_auth):
        api_key_auth.register_key("sk-test-123", "client-1", scopes=["read", "write"])
        result = await api_key_auth.authenticate("sk-test-123")
        assert result.authenticated is True
        assert result.client_id == "client-1"
        assert "read" in result.scopes
        assert "write" in result.scopes

    async def test_invalid_key(self, api_key_auth):
        result = await api_key_auth.authenticate("sk-invalid")
        assert result.authenticated is False
        assert "Invalid" in result.error

    async def test_empty_key(self, api_key_auth):
        result = await api_key_auth.authenticate("")
        assert result.authenticated is False
        assert "Missing" in result.error

    async def test_revoke_key(self, api_key_auth):
        api_key_auth.register_key("sk-revoke-me", "client-2")
        assert api_key_auth.revoke_key("sk-revoke-me") is True
        result = await api_key_auth.authenticate("sk-revoke-me")
        assert result.authenticated is False
        assert "revoked" in result.error.lower()

    async def test_revoke_nonexistent_key(self, api_key_auth):
        assert api_key_auth.revoke_key("sk-nonexistent") is False

    async def test_check_scope(self, api_key_auth):
        api_key_auth.register_key("sk-scoped", "client-3", scopes=["read"])
        result = await api_key_auth.authenticate("sk-scoped")
        assert api_key_auth.check_scope(result, "read") is True
        assert api_key_auth.check_scope(result, "admin") is False

    def test_hash_key_deterministic(self):
        h1 = APIKeyAuth.hash_key("test-key")
        h2 = APIKeyAuth.hash_key("test-key")
        assert h1 == h2

    def test_hash_key_different_keys(self):
        h1 = APIKeyAuth.hash_key("key-1")
        h2 = APIKeyAuth.hash_key("key-2")
        assert h1 != h2

    async def test_register_with_custom_rate_limit(self, api_key_auth):
        record = api_key_auth.register_key("sk-limited", "client-4", rate_limit=50)
        assert record.rate_limit == 50
        result = await api_key_auth.authenticate("sk-limited")
        assert result.metadata["rate_limit"] == 50


class TestOAuthAuth:
    async def test_issue_and_validate_token(self, oauth_auth):
        token = oauth_auth.issue_token("client-1", scopes=["read", "write"])
        result = await oauth_auth.authenticate(token)
        assert result.authenticated is True
        assert result.client_id == "client-1"

    async def test_invalid_token(self, oauth_auth):
        result = await oauth_auth.authenticate("invalid-token")
        assert result.authenticated is False

    async def test_empty_token(self, oauth_auth):
        result = await oauth_auth.authenticate("")
        assert result.authenticated is False
        assert "Missing" in result.error

    async def test_expired_token(self, oauth_auth):
        token = oauth_auth.issue_token("client-1", expires_in=-1)
        result = await oauth_auth.authenticate(token)
        assert result.authenticated is False
        assert "expired" in result.error.lower()

    async def test_token_scopes(self, oauth_auth):
        token = oauth_auth.issue_token("client-1", scopes=["admin"])
        result = await oauth_auth.authenticate(token)
        assert "admin" in result.scopes


class TestJWTAuthHS256:
    """JWTAuth in HS256 (symmetric) mode."""

    @pytest.fixture
    def jwt_auth(self):
        return JWTAuth(secret="super-secret", issuer="test-issuer")

    def _make_token(
        self,
        secret: str = "super-secret",
        sub: str = "client-1",
        scopes: list | None = None,
        issuer: str = "test-issuer",
        expires_in: int = 3600,
        extra: dict | None = None,
    ) -> str:
        import jwt, time
        payload = {
            "sub": sub,
            "scope": " ".join(scopes or ["read"]),
            "iss": issuer,
            "exp": time.time() + expires_in,
            "iat": time.time(),
            **(extra or {}),
        }
        return jwt.encode(payload, secret, algorithm="HS256")

    async def test_valid_token(self, jwt_auth):
        token = self._make_token()
        result = await jwt_auth.authenticate(token)
        assert result.authenticated is True
        assert result.client_id == "client-1"

    async def test_scopes_extracted(self, jwt_auth):
        token = self._make_token(scopes=["read", "write", "db:query"])
        result = await jwt_auth.authenticate(token)
        assert "db:query" in result.scopes

    async def test_scp_claim_variant(self, jwt_auth):
        import jwt, time
        payload = {"sub": "u1", "scp": ["read", "admin"], "iss": "test-issuer", "exp": time.time() + 3600}
        token = jwt.encode(payload, "super-secret", algorithm="HS256")
        result = await jwt_auth.authenticate(token)
        assert "admin" in result.scopes

    async def test_empty_token(self, jwt_auth):
        result = await jwt_auth.authenticate("")
        assert result.authenticated is False
        assert "Missing" in result.error

    async def test_bearer_prefix_stripped(self, jwt_auth):
        token = "Bearer " + self._make_token()
        result = await jwt_auth.authenticate(token)
        assert result.authenticated is True

    async def test_expired_token(self, jwt_auth):
        token = self._make_token(expires_in=-60)  # expired 60s ago, exceeds 30s leeway
        result = await jwt_auth.authenticate(token)
        assert result.authenticated is False
        assert "expired" in result.error.lower()

    async def test_wrong_secret(self, jwt_auth):
        token = self._make_token(secret="wrong-secret")
        result = await jwt_auth.authenticate(token)
        assert result.authenticated is False

    async def test_malformed_token(self, jwt_auth):
        result = await jwt_auth.authenticate("not.a.jwt")
        assert result.authenticated is False

    async def test_check_scope_pass(self, jwt_auth):
        token = self._make_token(scopes=["read", "db:write"])
        result = await jwt_auth.authenticate(token)
        assert jwt_auth.check_scope(result, "db:write") is True

    async def test_check_scope_fail(self, jwt_auth):
        token = self._make_token(scopes=["read"])
        result = await jwt_auth.authenticate(token)
        assert jwt_auth.check_scope(result, "admin") is False

    def test_missing_secret_and_jwks_raises(self):
        with pytest.raises(ValueError, match="secret"):
            JWTAuth()

    def test_both_secret_and_jwks_raises(self):
        with pytest.raises(ValueError, match="both"):
            JWTAuth(secret="s", jwks_uri="https://example.com/.well-known/jwks.json")


class TestJWTTokenVerifier:
    """JWTTokenVerifier adapts JWTAuth/APIKeyAuth to the SDK TokenVerifier."""

    SECRET = "x" * 40

    def _token(self, scopes: list[str], secret: str | None = None) -> str:
        return jwt.encode(
            {"sub": "client-9", "scope": " ".join(scopes), "exp": time.time() + 3600},
            secret or self.SECRET,
            algorithm="HS256",
        )

    async def test_valid_token_returns_access_token(self):
        v = JWTTokenVerifier(JWTAuth(secret=self.SECRET))
        at = await v.verify_token(self._token(["read", "db:read"]))
        assert at is not None
        assert at.client_id == "client-9"
        assert at.scopes == ["read", "db:read"]

    async def test_invalid_token_returns_none(self):
        v = JWTTokenVerifier(JWTAuth(secret=self.SECRET))
        assert await v.verify_token("not-a-jwt") is None

    async def test_wrong_secret_returns_none(self):
        v = JWTTokenVerifier(JWTAuth(secret=self.SECRET))
        assert await v.verify_token(self._token(["read"], secret="wrong" * 8)) is None

    async def test_adapts_api_key_auth(self):
        api = APIKeyAuth()
        api.register_key("sk-live-1", "client-7", scopes=["read"])
        v = JWTTokenVerifier(api)
        at = await v.verify_token("sk-live-1")
        assert at is not None and at.client_id == "client-7" and at.scopes == ["read"]
        assert await v.verify_token("sk-bogus") is None


class TestRequiresScope:
    """requires_scope reads the SDK per-request auth contextvar.

    The credential is NEVER a tool argument — it is the verified bearer token
    the SDK middleware places in the contextvar. These tests exercise that
    contract with real SDK objects (AuthenticatedUser / AccessToken), not mocks,
    via the shared ``grant_scopes`` helper.
    """

    async def test_allows_with_correct_scope(self):
        from tests.conftest import grant_scopes

        @requires_scope("read")
        async def my_tool() -> str:
            return "ok"

        with grant_scopes("read", "write"):
            assert await my_tool() == "ok"

    async def test_blocks_missing_scope(self):
        from tests.conftest import grant_scopes

        @requires_scope("admin")
        async def admin_tool() -> str:
            return "ok"

        with grant_scopes("read"):
            result = await admin_tool()
        assert "Forbidden" in result

    async def test_blocks_when_no_token_in_context(self):
        """No verified token (e.g. running under stdio) -> hard reject."""

        @requires_scope("read")
        async def secure_tool() -> str:
            return "ok"

        # No contextvar set: emulates stdio / unauthenticated request.
        result = await secure_tool()
        assert "Unauthorized" in result

    async def test_no_scope_only_checks_auth(self):
        from tests.conftest import grant_scopes

        @requires_scope("")
        async def any_authed() -> str:
            return "ok"

        with grant_scopes("read"):
            assert await any_authed() == "ok"

    async def test_credential_is_not_a_tool_argument(self):
        """A token kwarg must NOT satisfy auth — the old vulnerable path.

        Regression guard for the audit's harshest finding: the decorator no
        longer reads ``kwargs``, so a caller-supplied ``token`` argument cannot
        authenticate. With no verified token in context this must hard-reject
        even though a token-shaped kwarg is present.
        """

        @requires_scope("read")
        async def t(token: str = "") -> str:
            return "ok"

        result = await t(token="anything")
        assert "Unauthorized" in result


class TestAuthToolDecorator:
    """`EnhancedMCP.auth_tool` is a public, documented convenience wrapper
    (``@mcp.tool()`` + ``@requires_scope``). Exercise its documented path
    end-to-end through the real MCP dispatch and the real auth contextvar."""

    async def test_auth_tool_runs_with_scope_and_rejects_without_context(self):
        from mcp_toolkit.framework.base_server import EnhancedMCP
        from mcp_toolkit.framework.testing import MCPTestClient
        from tests.conftest import grant_scopes

        mcp = EnhancedMCP("auth-tool-probe")

        @mcp.auth_tool(required_scope="reports:read")
        async def get_report(name: str) -> str:
            return f"report:{name}"

        client = MCPTestClient(mcp)

        # With the required scope in context -> the tool body runs.
        with grant_scopes("reports:read"):
            ok = await client.call_tool("get_report", {"name": "q3"})
        assert ok == "report:q3"

        # No verified token in context (stdio / unauthenticated) -> hard reject.
        no_auth = await client.call_tool("get_report", {"name": "q3"})
        assert "Unauthorized" in str(no_auth)

        # Authenticated but missing the required scope -> Forbidden.
        with grant_scopes("other:scope"):
            forbidden = await client.call_tool("get_report", {"name": "q3"})
        assert "Forbidden" in str(forbidden)
