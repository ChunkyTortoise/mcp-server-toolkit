"""Transport bearer verification and SDK-context scope checks."""

import json
import logging
import time

import jwt
import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

from mcp_toolkit.framework.auth import AuthResult, _hash_id
from mcp_toolkit.framework.errors import Forbidden
from mcp_toolkit.framework.http_auth import JWTTokenVerifier, require_scope
from mcp_toolkit.framework.telemetry import TelemetryProvider

SECRET = "http-verifier-test-key-at-least-32-bytes"
RESOURCE = "http://127.0.0.1:8000/mcp"
ISSUER = "http://127.0.0.1:9000"


def token(**overrides):
    claims = {
        "sub": "reader@example.test",
        "aud": RESOURCE,
        "iss": ISSUER,
        "exp": time.time() + 300,
        "scope": "orders:read",
    }
    claims.update(overrides)
    if claims.get("sub") is None:
        claims.pop("sub", None)
    return jwt.encode(claims, SECRET, algorithm="HS256")


@pytest.fixture
def verifier():
    return JWTTokenVerifier(secret=SECRET, audience=RESOURCE, issuer=ISSUER)


async def test_valid_access_token_preserves_identity_and_resource(verifier):
    bearer = token()
    access = await verifier.verify_token(bearer)
    assert access is not None
    assert access.token == bearer
    assert access.client_id == "reader@example.test"
    assert access.subject == "reader@example.test"
    assert access.scopes == ["orders:read"]
    assert access.resource == RESOURCE
    assert access.claims["iss"] == ISSUER
    assert access.expires_at > time.time()


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": time.time() - 100},
        {"exp": None},
        {"exp": "4102444800"},
        {"exp": True},
        {"exp": float("inf")},
        {"exp": float("nan")},
        {"aud": "http://other.example/mcp"},
        {"iss": "http://other.example"},
    ],
)
async def test_invalid_claims_are_rejected(verifier, overrides):
    assert await verifier.verify_token(token(**overrides)) is None


async def test_missing_exp_is_rejected(verifier):
    claims = jwt.decode(token(), SECRET, algorithms=["HS256"], audience=RESOURCE)
    del claims["exp"]
    assert await verifier.verify_token(jwt.encode(claims, SECRET, algorithm="HS256")) is None


@pytest.mark.parametrize("bearer", ["", "forged", "Bearer invalid"])
async def test_malformed_token_returns_none(verifier, bearer):
    assert await verifier.verify_token(bearer) is None


@pytest.mark.parametrize(
    "claim,value", [("scope", "orders:read orders:write"), ("scp", ["orders:read", "orders:write"])]
)
async def test_scope_claim_formats(verifier, claim, value):
    claims = {"scope": ""}
    claims[claim] = value
    bearer = token(**claims)
    access = await verifier.verify_token(bearer)
    assert access.scopes == ["orders:read", "orders:write"]


async def test_audience_list_containing_resource_is_accepted(verifier):
    access = await verifier.verify_token(token(aud=["http://other.example", RESOURCE]))
    assert access.resource == RESOURCE


async def test_client_id_without_subject_remains_supported(verifier):
    access = await verifier.verify_token(token(sub=None, client_id="service-client"))
    assert access.client_id == "service-client"
    assert access.subject is None


async def test_no_identity_is_rejected(verifier):
    assert await verifier.verify_token(token(sub=None)) is None


@pytest.mark.parametrize(
    "claims",
    [{"aud": RESOURCE}, {"exp": time.time() + 100}, {"aud": RESOURCE, "exp": "4102444800"}],
)
async def test_verifier_checks_claims_even_if_authenticator_accepts(verifier, monkeypatch, claims):
    async def authenticate(_):
        return AuthResult(authenticated=True, client_id="client", metadata={"payload": claims})

    monkeypatch.setattr(verifier._auth, "authenticate", authenticate)
    assert await verifier.verify_token("opaque") is None


async def test_auth_audit_is_not_duplicated_and_has_no_raw_identity(verifier, caplog):
    with caplog.at_level(logging.INFO, logger="mcp_toolkit.auth.audit"):
        assert await verifier.verify_token(token()) is not None
    entries = [
        json.loads(r.getMessage()) for r in caplog.records if r.name == "mcp_toolkit.auth.audit"
    ]
    assert len(entries) == 1
    assert entries[0]["event"] == "jwt.accepted"
    assert entries[0]["client_hash"] == _hash_id("reader@example.test")
    assert "reader@example.test" not in caplog.text


def test_audience_is_required():
    with pytest.raises(ValueError, match="audience"):
        JWTTokenVerifier(secret=SECRET, audience="")


@pytest.mark.parametrize("scopes,allowed", [(["orders:write"], True), (["orders:read"], False)])
async def test_require_scope_uses_verified_context_and_hashes_subject(scopes, allowed):
    access = AccessToken(
        token="sensitive-bearer",
        client_id="client",
        subject="reader@example.test",
        scopes=scopes,
        expires_at=int(time.time()) + 300,
    )
    reset = auth_context_var.set(AuthenticatedUser(access))
    telemetry = TelemetryProvider("http-scope")
    try:
        async with telemetry.tool_call("cancel"):
            if allowed:
                require_scope("orders:write")
            else:
                with pytest.raises(Forbidden):
                    require_scope("orders:write")
    finally:
        auth_context_var.reset(reset)
    attrs = telemetry.spans[0].attributes
    assert attrs["mcp.subject"] == _hash_id("reader@example.test")
    assert "reader@example.test" not in json.dumps(attrs)
    assert "sensitive-bearer" not in json.dumps(attrs)


def test_require_scope_without_auth_context_refuses():
    with pytest.raises(Forbidden):
        require_scope("orders:read")


@pytest.mark.parametrize(
    "claims",
    [
        {"sub": None, "client_id": 123},
        {"sub": None, "client_id": ["not-a-client"]},
        {"scope": [123]},
    ],
)
async def test_malformed_identity_and_scopes_return_none(verifier, claims):
    assert await verifier.verify_token(token(**claims)) is None


@pytest.mark.parametrize(
    "claims",
    [
        {"sub": "", "client_id": "reader@example.test"},
        {"scope": 123},
        {"scope": {"orders:read": True}},
        {"scope": True},
    ],
)
async def test_empty_subject_and_nonstandard_scope_types_are_rejected(verifier, claims):
    assert await verifier.verify_token(token(**claims)) is None


async def test_transport_specific_rejection_has_correlatable_hashed_identity(verifier, caplog):
    with caplog.at_level(logging.INFO, logger="mcp_toolkit.auth.audit"):
        assert await verifier.verify_token(token(exp="4102444800")) is None
    entries = [
        json.loads(r.getMessage()) for r in caplog.records if r.name == "mcp_toolkit.auth.audit"
    ]
    assert [entry["event"] for entry in entries] == ["jwt.accepted", "jwt.rejected"]
    assert {entry["client_hash"] for entry in entries} == {_hash_id("reader@example.test")}
    assert "reader@example.test" not in caplog.text


@pytest.mark.parametrize(
    "identities",
    [
        [("issuer-a", "same", "same"), ("issuer-b", "same", "same")],
        [("issuer-a", "same", "same"), ("issuer-a", None, "same")],
        [("issuer-a", None, "client-a"), ("issuer-a", None, "client-b")],
    ],
)
async def test_rate_buckets_separate_issuers_and_subject_client_namespaces(identities):
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp_toolkit.framework.base_server import EnhancedMCP
    from mcp_toolkit.framework.testing import MCPTestClient

    server = EnhancedMCP("identity-namespaces")

    @server.rate_limited_tool(max_calls=1, window_seconds=60)
    async def read(caller_id: str) -> str:
        return "ok"

    async def invoke(identity, caller):
        issuer, subject, client_id = identity
        access = AccessToken(
            token="context-only",
            client_id=client_id,
            subject=subject,
            scopes=["orders:read"],
            claims={"iss": issuer},
        )
        reset = auth_context_var.set(AuthenticatedUser(access))
        try:
            return await MCPTestClient(server).call_tool("read", {"caller_id": caller})
        finally:
            auth_context_var.reset(reset)

    assert await invoke(identities[0], "forged-first") == "ok"
    assert await invoke(identities[1], "forged-second") == "ok"
    with pytest.raises(ToolError, match="Rate limited"):
        await invoke(identities[0], "rotated-caller")
    for span, identity in zip(server.telemetry.spans, [*identities, identities[0]]):
        assert span.attributes["mcp.subject"] == _hash_id(identity[1] or identity[2])
