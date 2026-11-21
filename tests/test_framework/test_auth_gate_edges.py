"""Gate behaviors the JSONL corpus format cannot express.

The corpus harness signs one token per case with a fixed far-future ``exp`` and passes a
single ``token`` argument, so three things are tested here instead: expiry relative to
the leeway window, two credential arguments competing in one call, and a tool that asks
for authentication only. The last test pins an open owner decision as a strict xfail.
"""

import time

import jwt
import pytest

from mcp_toolkit.framework.auth import JWTAuth, requires_scope
from mcp_toolkit.framework.errors import Forbidden, Unauthorized

SECRET = "gate-edge-test-secret-32-bytes-minimum!!"


def _token(scope: str = "read", **extra) -> str:
    claims = {"sub": "client-1", "scope": scope, "exp": time.time() + 3600, **extra}
    return jwt.encode(claims, SECRET, algorithm="HS256")


@pytest.mark.parametrize(
    "seconds_past_exp,accepted",
    [(-60, True), (20, True), (40, False), (3600, False)],
    ids=["not-expired", "expired-inside-leeway", "expired-past-leeway", "expired-an-hour-ago"],
)
async def test_expiry_is_honoured_up_to_the_leeway(seconds_past_exp, accepted):
    """Default leeway is 30 seconds: a token is accepted until exp + 30 s and not after."""
    auth = JWTAuth(secret=SECRET)
    result = await auth.authenticate(_token(exp=time.time() - seconds_past_exp))
    assert result.authenticated is accepted
    if not accepted:
        assert result.error == "Token expired"


async def test_zero_leeway_refuses_a_token_expired_by_seconds():
    auth = JWTAuth(secret=SECRET, leeway=0)
    result = await auth.authenticate(_token(exp=time.time() - 5))
    assert result.authenticated is False


@pytest.mark.parametrize("other_arg", ["api_key", "authorization"])
async def test_low_scope_token_is_not_upgraded_by_a_second_credential(other_arg):
    """With a non-empty ``token``, an admin token in another credential argument is ignored."""
    auth = JWTAuth(secret=SECRET)
    ran: list[bool] = []

    @requires_scope(auth, "admin")
    async def probe(token: str = "", api_key: str = "", authorization: str = "") -> str:
        ran.append(True)
        return "ok"

    with pytest.raises(Forbidden):
        await probe(token=_token("read"), **{other_arg: _token("admin")})
    assert ran == []


async def test_forged_token_is_not_rescued_by_a_valid_second_credential():
    """A bad ``token`` fails the call even when ``authorization`` holds a valid admin token."""
    auth = JWTAuth(secret=SECRET)
    ran: list[bool] = []

    @requires_scope(auth, "admin")
    async def probe(token: str = "", authorization: str = "") -> str:
        ran.append(True)
        return "ok"

    forged = jwt.encode({"sub": "x", "scope": "admin", "exp": time.time() + 60}, "k" * 32, "HS256")
    with pytest.raises(Unauthorized):
        await probe(token=forged, authorization=_token("admin"))
    assert ran == []


async def test_empty_required_scope_still_requires_a_valid_token():
    """``requires_scope(auth, "")`` skips the scope check, not authentication."""
    auth = JWTAuth(secret=SECRET)
    ran: list[bool] = []

    @requires_scope(auth, "")
    async def probe(token: str = "") -> str:
        ran.append(True)
        return "ok"

    for bad in ("", "forged", _token(exp=time.time() - 3600)):
        with pytest.raises(Unauthorized):
            await probe(token=bad)
    assert ran == []
    assert await probe(token=_token(scope="")) == "ok"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "open owner decision (TODO(Cayman) in JWTAuth.authenticate): a signed token with no "
        "sub, client_id or azp is accepted with client_id=None, while the HTTP gateway "
        "verifier refuses it"
    ),
)
async def test_token_without_subject_is_refused():
    claims = {"scope": "admin", "exp": time.time() + 3600}
    result = await JWTAuth(secret=SECRET).authenticate(jwt.encode(claims, SECRET, "HS256"))
    assert result.authenticated is False
