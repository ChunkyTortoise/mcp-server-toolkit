"""Tests for authentication module."""

from mcp_toolkit.framework.auth import APIKeyAuth


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
