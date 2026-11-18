"""Refusal messages for JWT failures name the failure class and nothing else."""

import time

import jwt
import pytest

from mcp_toolkit.framework.auth import JWTAuth, _jwt_error_message

SECRET = "error-message-test-secret-32-bytes-min!!"


def _claims(**extra) -> dict:
    return {"sub": "client-1", "scope": "read", "exp": time.time() + 3600, **extra}


def _cases() -> list:
    now = time.time()
    return [
        pytest.param(
            jwt.encode(_claims(), SECRET, algorithm="HS512"),
            "Token algorithm not allowed",
            id="right-secret-wrong-algorithm",
        ),
        pytest.param(
            jwt.encode(_claims(sub=["admin"]), SECRET, algorithm="HS256"),
            "Invalid token subject",
            id="subject-is-a-list",
        ),
        pytest.param(
            jwt.encode(_claims(nbf=now + 3600), SECRET, algorithm="HS256"),
            "Token not yet valid",
            id="nbf-in-the-future",
        ),
        pytest.param(
            jwt.encode(_claims(iat=now + 3600), SECRET, algorithm="HS256"),
            "Token not yet valid",
            id="iat-in-the-future",
        ),
    ]


@pytest.mark.parametrize("token,expected", _cases())
async def test_refusal_names_the_failure_class(token, expected):
    result = await JWTAuth(secret=SECRET).authenticate(token)
    assert result.authenticated is False
    assert result.error == expected


@pytest.mark.parametrize("token,expected", _cases())
async def test_refusal_does_not_echo_token_or_config(token, expected):
    """The message is a fixed string: no claim value, algorithm name or secret."""
    result = await JWTAuth(secret=SECRET).authenticate(token)
    assert result.error is not None
    for leaked in (SECRET, "HS256", "HS512", "admin", "client-1", token):
        assert leaked not in result.error


def test_existing_messages_are_unchanged():
    assert _jwt_error_message(jwt.ExpiredSignatureError("x")) == "Token expired"
    assert _jwt_error_message(jwt.InvalidSignatureError("x")) == "Invalid token signature"
    assert _jwt_error_message(jwt.InvalidAudienceError("x")) == "Invalid token audience"
    assert _jwt_error_message(jwt.InvalidIssuerError("x")) == "Invalid token issuer"
    assert _jwt_error_message(jwt.DecodeError("x")) == "Malformed token"
    assert _jwt_error_message(RuntimeError("detail")) == "Token validation failed"
