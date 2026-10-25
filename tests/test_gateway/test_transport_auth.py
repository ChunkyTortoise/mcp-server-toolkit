"""Live HTTP gateway plus SDK middleware, session and verified-identity contracts."""

import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import anyio
import httpx
import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from mcp_toolkit.framework.auth import _hash_id
from mcp_toolkit.framework.http_auth import require_scope
from mcp_toolkit.gateway import create_server
from mcp_toolkit.gateway.app import HTTP_OPTIONS

ROOT = Path(__file__).resolve().parents[2]
GATEWAY = [sys.executable, "-m", "mcp_toolkit.gateway"]
ISSUER = "http://127.0.0.1:9000"
ACCEPT = {"Accept": "application/json, text/event-stream"}
PROTOCOL = "2025-11-25"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def mint(server, **overrides):
    claims = {
        "sub": "reader@example.test",
        "client_id": "shared-client",
        "iss": ISSUER,
        "aud": server["url"],
        "exp": time.time() + 300,
        "scope": "orders:read",
    }
    claims.update(overrides)
    if claims["exp"] is None:
        del claims["exp"]
    return jwt.encode(claims, server["secret"], algorithm="HS256")


@asynccontextmanager
async def running_example(tmp_path, *, secret=None, jwks_uri=None):
    port = free_port()
    url = f"http://127.0.0.1:{port}/mcp"
    env = {k: v for k, v in os.environ.items() if not k.startswith("MCP_")}
    env.update(
        PYTHONPATH=str(ROOT),
        PYTHONDONTWRITEBYTECODE="1",
        MCP_HOST="127.0.0.1",
        MCP_PORT=str(port),
        MCP_RESOURCE_URL=url,
        MCP_ISSUER=ISSUER,
    )
    if jwks_uri:
        env["MCP_JWKS_URI"] = jwks_uri
        assert "MCP_JWT_SECRET" not in env
    else:
        secret = secret or secrets.token_hex(32)
        env["MCP_JWT_SECRET"] = secret
    log_path = tmp_path / "http-example.log"
    with log_path.open("w") as output:
        process = subprocess.Popen(
            GATEWAY,
            cwd=ROOT,
            env=env,
            stdout=output,
            stderr=output,
        )
        try:
            with anyio.fail_after(20):
                async with httpx.AsyncClient() as client:
                    while True:
                        if process.poll() is not None:
                            raise RuntimeError(log_path.read_text())
                        try:
                            response = await client.post(url)
                            if response.status_code == 401:
                                break
                        except httpx.ConnectError:
                            pass
                        await anyio.sleep(0.05)
            yield {"url": url, "secret": secret, "env": env}
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.fixture
async def live_server(tmp_path):
    async with running_example(tmp_path) as server:
        yield server


async def test_missing_bearer_has_protected_resource_metadata(live_server):
    async with httpx.AsyncClient() as client:
        response = await client.post(live_server["url"])
        assert response.status_code == 401
        header = response.headers["www-authenticate"]
        metadata_url = re.search(r'resource_metadata="([^"]+)"', header).group(1)
        metadata = await client.get(metadata_url)
        assert metadata.status_code == 200
        assert metadata.json()["resource"] == live_server["url"]


@pytest.mark.parametrize("case", ["forged", "wrong-audience", "missing-exp", "expired"])
async def test_invalid_bearer_gets_401(live_server, case):
    overrides = {
        "wrong-audience": {"aud": "http://other.example/mcp"},
        "missing-exp": {"exp": None},
        "expired": {"exp": time.time() - 100},
    }
    bearer = "forged" if case == "forged" else mint(live_server, **overrides[case])
    async with httpx.AsyncClient() as client:
        response = await client.post(
            live_server["url"], headers={"Authorization": f"Bearer {bearer}"}
        )
    assert response.status_code == 401


async def call_example(url, bearer):
    with anyio.fail_after(15):
        session_ids = []

        async def record_session_id(response):
            session_ids.append(response.headers.get("mcp-session-id"))

        async with httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {bearer}"},
            event_hooks={"response": [record_session_id]},
        ) as http:
            async with streamable_http_client(url, http_client=http) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    assert session_ids and session_ids[0]
                    tools = {t.name: t for t in (await session.list_tools()).tools}
                    assert set(tools) == {"get_order", "cancel_order"}
                    for tool in tools.values():
                        assert set(tool.input_schema.get("properties", {})) == {"order_id"}
                    assert tools["get_order"].annotations.read_only_hint is True
                    assert tools["cancel_order"].annotations.destructive_hint is True
                    result = await session.call_tool("get_order", {"order_id": "42"})
                    assert result.is_error is False
                    assert result.content[0].text == "order 42: shipped"
                    result = await session.call_tool("cancel_order", {"order_id": "42"})
                    assert result.is_error is True
                    assert "Forbidden:" in result.content[0].text


async def test_sdk_client_authorized_read_and_per_tool_scope_refusal(live_server):
    await call_example(live_server["url"], mint(live_server))


@pytest.fixture
def local_jwks():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="test-key", alg="RS256", use="sig")
    document = json.dumps({"keys": [jwk]}).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/jwks":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(document)))
            self.end_headers()
            self.wfile.write(document)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield key, f"http://127.0.0.1:{server.server_port}/jwks"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def test_real_jwks_path_without_hmac_secret(tmp_path, local_jwks):
    key, jwks_uri = local_jwks
    async with running_example(tmp_path, jwks_uri=jwks_uri) as server:
        claims = {
            "sub": "jwks-reader",
            "aud": server["url"],
            "iss": ISSUER,
            "scope": "orders:read",
            "exp": time.time() + 300,
        }
        bearer = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})
        await call_example(server["url"], bearer)
        claims["aud"] = "http://other.example/mcp"
        wrong = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})
        async with httpx.AsyncClient() as client:
            response = await client.post(
                server["url"], headers={"Authorization": f"Bearer {wrong}"}
            )
        assert response.status_code == 401


@asynccontextmanager
async def counted_server(**http_options):
    secret = secrets.token_hex(32)
    url = "http://127.0.0.1:8000/mcp"
    server = create_server(secret=secret, resource_url=url, issuer=ISSUER)
    calls = {"probe": 0, "cached": 0}

    @server.rate_limited_tool(max_calls=2, window_seconds=60)
    async def probe(caller_id: str = "untrusted") -> str:
        require_scope("orders:read")
        calls["probe"] += 1
        return "ok"

    @server.cached_tool(ttl=60)
    async def cached_report(report_id: str) -> str:
        require_scope("orders:write")
        calls["cached"] += 1
        return f"report {report_id} for writers"

    app = server.streamable_http_app(**{**HTTP_OPTIONS, **http_options})
    async with server.session_manager.run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000"
        ) as client:
            yield {"server": server, "client": client, "calls": calls, "secret": secret, "url": url}


def headers(bearer=None, session=None):
    result = {**ACCEPT, "MCP-Protocol-Version": PROTOCOL}
    if bearer:
        result["Authorization"] = f"Bearer {bearer}"
    if session:
        result["Mcp-Session-Id"] = session
    return result


async def initialize(server, bearer):
    response = await server["client"].post(
        "/mcp",
        headers=headers(bearer),
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "contract", "version": "1"},
            },
        },
    )
    assert response.status_code == 200, response.text
    session = response.headers["Mcp-Session-Id"]
    response = await server["client"].post(
        "/mcp",
        headers=headers(bearer, session),
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert response.status_code == 202
    return session


async def probe(server, bearer, session, caller_id="untrusted"):
    return await server["client"].post(
        "/mcp",
        headers=headers(bearer, session),
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "probe", "arguments": {"caller_id": caller_id}},
        },
    )


async def test_loopback_gateway_refuses_a_foreign_host_header_with_421():
    async with counted_server() as server:
        response = await server["client"].post(
            "/mcp",
            headers={**headers(mint(server)), "Host": "attacker.example"},
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
        assert response.status_code == 421
        assert server["calls"] == {"probe": 0, "cached": 0}


async def test_endpoint_scope_is_403_before_handler_dispatch():
    async with counted_server() as server:
        bearer = mint(server, scope="orders:write")
        response = await probe(server, bearer, None)
        assert response.status_code == 403
        assert response.json()["error"] == "insufficient_scope"
        assert server["calls"]["probe"] == 0
        assert server["server"].telemetry.spans == []


async def test_other_subject_session_is_404_without_handler_dispatch():
    async with counted_server() as server:
        owner = mint(server, sub="owner@example.test")
        session = await initialize(server, owner)
        response = await probe(server, mint(server, sub="other@example.test"), session)
        assert response.status_code == 404
        assert server["calls"]["probe"] == 0
        assert server["server"].telemetry.spans == []


async def test_session_without_authorization_is_401():
    async with counted_server() as server:
        session = await initialize(server, mint(server))
        response = await probe(server, None, session)
        assert response.status_code == 401
        assert server["calls"]["probe"] == 0


async def test_same_subject_refreshed_token_keeps_session():
    async with counted_server() as server:
        session = await initialize(server, mint(server, jti="old"))
        response = await probe(server, mint(server, jti="new"), session)
        assert response.status_code == 200
        assert response.json()["result"]["isError"] is False
        assert server["calls"]["probe"] == 1


@pytest.mark.parametrize("json_response", [True, False], ids=["json", "sse"])
async def test_http_rate_limit_uses_verified_subject_and_spans_hash_it(json_response):
    async with counted_server(json_response=json_response) as server:
        bearer = mint(server)
        session = await initialize(server, bearer)
        results = [await probe(server, bearer, session, f"forged-{i}") for i in range(3)]
        assert [rpc_result(r, json_response)["isError"] for r in results] == [False, False, True]
        assert server["calls"]["probe"] == 2
        other = mint(server, sub="other@example.test")
        other_session = await initialize(server, other)
        response = await probe(server, other, other_session, "forged-0")
        assert rpc_result(response, json_response)["isError"] is False
        spans = server["server"].telemetry.spans
        assert [s.attributes["mcp.subject"] for s in spans] == [
            *[_hash_id("reader@example.test")] * 3,
            _hash_id("other@example.test"),
        ]
        serialized = json.dumps([s.attributes for s in spans])
        assert "reader@example.test" not in serialized
        assert "other@example.test" not in serialized
        assert bearer not in serialized
        assert "forged-" not in serialized


def test_cli_missing_key_source_exits_clearly():
    env = {k: v for k, v in os.environ.items() if not k.startswith("MCP_")}
    result = subprocess.run(
        GATEWAY,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "set MCP_JWKS_URI, or MCP_JWT_SECRET" in result.stderr


def test_cli_demo_token_is_five_minutes_and_resource_bound():
    secret = secrets.token_hex(32)
    resource = "http://127.0.0.1:8765/mcp"
    env = {k: v for k, v in os.environ.items() if not k.startswith("MCP_")}
    env.update(MCP_JWT_SECRET=secret, MCP_RESOURCE_URL=resource, MCP_ISSUER=ISSUER)
    before = int(time.time())
    result = subprocess.run(
        [
            *GATEWAY,
            "--print-demo-token",
            "orders:read orders:write",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    claims = jwt.decode(
        result.stdout.strip(), secret, algorithms=["HS256"], audience=resource, issuer=ISSUER
    )
    assert claims["scope"] == "orders:read orders:write"
    assert before + 300 <= claims["exp"] <= int(time.time()) + 300


def test_cli_demo_minting_is_unavailable_with_only_jwks():
    env = {k: v for k, v in os.environ.items() if not k.startswith("MCP_")}
    env["MCP_JWKS_URI"] = "http://127.0.0.1:9000/jwks"
    result = subprocess.run(
        [
            *GATEWAY,
            "--print-demo-token",
            "orders:read",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "needs MCP_JWT_SECRET" in result.stderr
    assert result.stdout == ""


async def call_named_tool(server, bearer, session, name, arguments):
    return await server["client"].post(
        "/mcp",
        headers=headers(bearer, session),
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )


def rpc_result(response, json_response):
    """The JSON-RPC result, after pinning the response mode the server was built for."""
    content_type = response.headers["content-type"]
    expected = "application/json" if json_response else "text/event-stream"
    assert content_type.startswith(expected), content_type
    if not json_response:
        data = [line[5:] for line in response.text.splitlines() if line.startswith("data:")]
        return json.loads(data[-1])["result"]
    return response.json()["result"]


@pytest.mark.parametrize("json_response", [True, False], ids=["json", "sse"])
@pytest.mark.parametrize(
    "initial_scope,current_scope,refused",
    [
        ("orders:read orders:write", "orders:read", True),
        ("orders:read", "orders:read orders:write", False),
    ],
)
async def test_per_tool_scope_uses_current_request_token(
    initial_scope, current_scope, refused, json_response
):
    async with counted_server(json_response=json_response) as server:
        session = await initialize(server, mint(server, scope=initial_scope, jti="initial"))
        current = mint(server, scope=current_scope, jti="replacement")
        response = await call_named_tool(
            server, current, session, "cancel_order", {"order_id": "42"}
        )
        assert response.status_code == 200
        result = rpc_result(response, json_response)
        assert result["isError"] is refused
        if refused:
            assert "Forbidden:" in result["content"][0]["text"]
        assert server["server"].telemetry.spans[-1].attributes["tool.outcome"] == (
            "forbidden" if refused else "ok"
        )


async def test_expired_initial_write_token_does_not_grant_scope_to_new_read_token():
    async with counted_server() as server:
        expiry = int(time.time()) + 2
        initial = mint(server, scope="orders:read orders:write", exp=expiry)
        session = await initialize(server, initial)
        await anyio.sleep(max(0, expiry - time.time() + 0.05))
        old = await call_named_tool(server, initial, session, "cancel_order", {"order_id": "42"})
        assert old.status_code == 401
        current = await call_named_tool(
            server, mint(server), session, "cancel_order", {"order_id": "42"}
        )
        assert current.status_code == 200
        assert current.json()["result"]["isError"] is True
        assert "Forbidden:" in current.json()["result"]["content"][0]["text"]


@pytest.mark.parametrize("json_response", [True, False], ids=["json", "sse"])
async def test_cached_tool_refuses_authenticated_http_instead_of_sharing_authorized_data(
    json_response,
):
    async with counted_server(json_response=json_response) as server:
        writer = mint(server, sub="writer@example.test", scope="orders:read orders:write")
        reader = mint(server, sub="reader@example.test")
        writer_session = await initialize(server, writer)
        reader_session = await initialize(server, reader)
        for bearer, session in [(writer, writer_session), (reader, reader_session)]:
            response = await call_named_tool(
                server, bearer, session, "cached_report", {"report_id": "1"}
            )
            assert response.status_code == 200
            result = rpc_result(response, json_response)
            assert result["isError"] is True
            assert "authenticated HTTP" in result["content"][0]["text"]
        assert server["calls"]["cached"] == 0


def test_example_launcher_runs_the_packaged_gateway():
    result = subprocess.run(
        [sys.executable, str(ROOT / "examples/http_server.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("usage: mcp-toolkit-gateway")
