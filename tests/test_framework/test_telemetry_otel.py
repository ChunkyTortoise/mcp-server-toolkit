"""One OTel span per toolkit-decorated call, classified by outcome, with no secrets in it.

Also proves the console exporter fallback stays off stdout, the JSON-RPC channel of a
stdio server.
"""

import hashlib
import json
import logging
import sys
import textwrap
import time

import anyio
import jwt
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

pytest.importorskip("opentelemetry.sdk")
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402

from mcp_toolkit.framework.auth import JWTAuth  # noqa: E402
from mcp_toolkit.framework.base_server import EnhancedMCP  # noqa: E402
from mcp_toolkit.framework.telemetry import MAX_SPAN_RECORDS  # noqa: E402
from mcp_toolkit.framework.testing import MCPTestClient  # noqa: E402

SECRET = "otel-test-secret-at-least-32-bytes!!"


def _token(scope: str = "db:read", exp_delta: float = 3600) -> str:
    return jwt.encode(
        {"sub": "agent-7", "scope": scope, "exp": time.time() + exp_delta},
        SECRET,
        algorithm="HS256",
    )


@pytest.fixture
def exporter():
    return InMemorySpanExporter()


@pytest.fixture
def server(exporter):
    mcp = EnhancedMCP("otel-test")
    mcp.telemetry.initialize(span_exporter=exporter)
    auth = JWTAuth(secret=SECRET)

    @mcp.cached_tool(ttl=60)
    async def lookup(key: str) -> str:
        if key == "boom":
            raise RuntimeError("handler failed")
        return f"value:{key}"

    @mcp.rate_limited_tool(max_calls=1, window_seconds=60)
    async def ping(caller_id: str = "c1") -> str:
        return "pong"

    @mcp.auth_tool(auth, required_scope="db:read")
    async def run_sql(sql: str, token: str = "") -> str:
        return "rows"

    return mcp


def _spans(exporter):
    return [(s.name, dict(s.attributes or {})) for s in exporter.get_finished_spans()]


async def test_one_span_per_call_with_outcome(server, exporter):
    client = MCPTestClient(server)

    await client.call_tool_result("lookup", {"key": "a"})
    await client.call_tool_result("lookup", {"key": "a"})
    await client.call_tool_result("lookup", {"key": "boom"})
    await client.call_tool_result("ping", {})
    await client.call_tool_result("ping", {})
    await client.call_tool_result("run_sql", {"sql": "select 1", "token": _token()})
    await client.call_tool_result("run_sql", {"sql": "select 1", "token": "garbage"})
    await client.call_tool_result("run_sql", {"sql": "select 1", "token": _token("other")})

    spans = _spans(exporter)
    assert [(n, a["tool.outcome"]) for n, a in spans] == [
        ("tool.lookup", "ok"),
        ("tool.lookup", "ok"),
        ("tool.lookup", "error"),
        ("tool.ping", "ok"),
        ("tool.ping", "rate_limited"),
        ("tool.run_sql", "ok"),
        ("tool.run_sql", "unauthorized"),
        ("tool.run_sql", "forbidden"),
    ]
    for _, attrs in spans:
        assert attrs["tool.success"] is (attrs["tool.outcome"] == "ok")
        assert attrs["tool.name"]
    assert [a["cache_hit"] for n, a in spans if n == "tool.lookup" and a["tool.outcome"] == "ok"] == [
        False,
        True,
    ]


async def test_subject_attribute_is_sub_hash_when_token_parsed_and_empty_otherwise(server, exporter):
    client = MCPTestClient(server)
    await client.call_tool_result("run_sql", {"sql": "x", "token": _token()})
    await client.call_tool_result("run_sql", {"sql": "x", "token": _token("other")})
    await client.call_tool_result("run_sql", {"sql": "x", "token": "garbage"})
    await client.call_tool_result("run_sql", {"sql": "x", "token": _token(exp_delta=-3600)})
    await client.call_tool_result("run_sql", {"sql": "x", "token": ""})

    # Spans usually leave the host, so they carry a hash prefix of sub, never sub itself.
    sub_hash = hashlib.sha256(b"agent-7").hexdigest()[:16]
    subjects = [a["mcp.subject"] for _, a in _spans(exporter)]
    assert subjects == [sub_hash, sub_hash, "", "", ""]
    assert "agent-7" not in json.dumps(_spans(exporter), default=str)
    # Spans of tools without an auth guard carry no subject attribute at all.
    await client.call_tool_result("lookup", {"key": "k"})
    assert "mcp.subject" not in _spans(exporter)[-1][1]


async def test_spans_and_audit_lines_never_hold_token_or_arguments(server, exporter, caplog):
    token = _token()
    bad_token = "forged-token-0123456789"
    sql = "SELECT secret_column FROM hidden_table"
    client = MCPTestClient(server)
    with caplog.at_level(logging.DEBUG, logger="mcp_toolkit.auth.audit"):
        await client.call_tool_result("run_sql", {"sql": sql, "token": token})
        await client.call_tool_result("run_sql", {"sql": sql, "token": bad_token})
        await client.call_tool_result("run_sql", {"sql": sql, "token": _token("other")})
        await client.call_tool_result("ping", {"caller_id": "caller-xyz"})
        await client.call_tool_result("ping", {"caller_id": "caller-xyz"})

    audit_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "rate_limit.rejected" in audit_text
    assert "jwt.rejected" in audit_text
    assert "scope.denied" in audit_text
    span_text = json.dumps(_spans(exporter), default=str)
    otel_text = "".join(s.to_json() for s in exporter.get_finished_spans())
    # The caller id is a tool argument, so the audit line carries only a hash prefix.
    caller_hash = hashlib.sha256(b"caller-xyz").hexdigest()[:16]
    assert f'"caller_hash": "{caller_hash}"' in audit_text
    for secret in (token, bad_token, sql, "secret_column", "hidden_table", "caller-xyz"):
        for text in (audit_text, span_text, otel_text):
            assert secret not in text


async def test_in_memory_span_records_are_bounded(server):
    client = MCPTestClient(server)
    for i in range(MAX_SPAN_RECORDS + 25):
        await client.call_tool("lookup", {"key": str(i)})
    assert len(server.telemetry.spans) == MAX_SPAN_RECORDS


async def test_default_server_has_no_otel_and_still_records_outcomes():
    mcp = EnhancedMCP("plain")

    @mcp.cached_tool()
    async def f() -> str:
        return "x"

    await MCPTestClient(mcp).call_tool("f", {})
    assert mcp.telemetry.spans[0].attributes["tool.outcome"] == "ok"


SERVER_SCRIPT = textwrap.dedent(
    """
    from mcp_toolkit import EnhancedMCP

    mcp = EnhancedMCP("stdio-otel")
    mcp.telemetry.initialize(use_otel=True)

    @mcp.cached_tool()
    async def echo(text: str) -> str:
        return text

    mcp.run()
    """
)


async def test_stdio_stays_clean_with_use_otel_and_no_otlp_endpoint(tmp_path):
    script = tmp_path / "server.py"
    script.write_text(SERVER_SCRIPT)
    errlog = tmp_path / "stderr.log"
    root = __import__("pathlib").Path(__file__).resolve().parents[2]
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(script)],
        cwd=str(tmp_path),
        env={
            "PYTHONPATH": str(root),
            "PYTHONDONTWRITEBYTECODE": "1",
            "OTEL_BSP_SCHEDULE_DELAY": "100",
        },
    )
    with errlog.open("w") as err, anyio.fail_after(30):
        async with stdio_client(params, errlog=err) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                for _ in range(2):
                    result = await session.call_tool("echo", {"text": "hi"})
                    assert not result.isError
                    assert result.content[0].text == "hi"
                await anyio.sleep(0.5)
    # A corrupted stdout would have failed the round trip above (JSON-RPC parse errors).
    # The spans themselves went to stderr.
    assert "tool.echo" in errlog.read_text()
