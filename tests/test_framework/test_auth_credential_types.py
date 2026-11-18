"""Non-string credentials must be refused like any other bad credential.

A direct Python caller can hand ``authenticate`` an int, list, dict or bytes. Each
must come back as an unauthenticated result with one audit line, not as a raw
``AttributeError`` or ``TypeError`` that skips the audit log.
"""

import json
import logging
import time

import jwt
import pytest

from mcp_toolkit.framework.auth import APIKeyAuth, JWTAuth, requires_scope
from mcp_toolkit.framework.errors import Unauthorized

SECRET = "credential-type-test-secret-32-bytes-min"
AUDIT_LOGGER = "mcp_toolkit.auth.audit"


def _valid_token(scope: str = "admin") -> str:
    claims = {"sub": "client-1", "scope": scope, "exp": time.time() + 3600}
    return jwt.encode(claims, SECRET, algorithm="HS256")


def _non_string_credentials() -> list:
    token = _valid_token()
    return [
        pytest.param(12345, id="int"),
        pytest.param(True, id="bool"),
        pytest.param([token], id="list-holding-a-valid-token"),
        pytest.param({"token": token}, id="dict-holding-a-valid-token"),
        pytest.param(token.encode(), id="valid-token-as-bytes"),
    ]


def _audit_entries(caplog) -> list[dict]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == AUDIT_LOGGER]


@pytest.mark.parametrize("credential", _non_string_credentials())
async def test_jwt_auth_refuses_non_string_token_with_audit_line(credential, caplog):
    auth = JWTAuth(secret=SECRET)
    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        result = await auth.authenticate(credential)

    assert result.authenticated is False
    assert result.scopes == []
    assert result.error == "Malformed token"
    entries = _audit_entries(caplog)
    assert [e["event"] for e in entries] == ["jwt.rejected"]
    assert entries[0]["error"] == "non_string_token"


@pytest.mark.parametrize("credential", _non_string_credentials())
async def test_api_key_auth_refuses_non_string_key_with_audit_line(credential, caplog):
    auth = APIKeyAuth()
    auth.register_key("real-key", "client-1", scopes=["admin"])
    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER):
        result = await auth.authenticate(credential)

    assert result.authenticated is False
    assert result.scopes == []
    assert result.error == "Invalid API key"
    entries = _audit_entries(caplog)
    assert [e["event"] for e in entries] == ["api_key.rejected"]
    assert entries[0]["error"] == "non_string_key"


@pytest.mark.parametrize("credential", _non_string_credentials())
@pytest.mark.parametrize("kind", ["jwt", "api_key"])
async def test_requires_scope_raises_unauthorized_for_non_string_credential(kind, credential):
    if kind == "jwt":
        auth: JWTAuth | APIKeyAuth = JWTAuth(secret=SECRET)
    else:
        auth = APIKeyAuth()
        auth.register_key("real-key", "client-1", scopes=["admin"])
    ran: list[bool] = []

    @requires_scope(auth, "admin")
    async def probe(token=""):
        ran.append(True)
        return "ok"

    with pytest.raises(Unauthorized):
        await probe(token=credential)
    assert ran == []


async def test_string_credentials_still_pass():
    """Control: the type check does not refuse a valid string credential."""
    jwt_result = await JWTAuth(secret=SECRET).authenticate(_valid_token())
    assert jwt_result.authenticated is True
    assert jwt_result.scopes == ["admin"]

    keys = APIKeyAuth()
    keys.register_key("real-key", "client-1", scopes=["admin"])
    key_result = await keys.authenticate("real-key")
    assert key_result.authenticated is True
