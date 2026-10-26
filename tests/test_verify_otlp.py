"""Tests for the OTLP verification script (examples/observability/verify_otlp.py).

The query/check half runs against a Jaeger-compatible stub over httpx
MockTransport. The emit half runs the real OTel SDK exporter against a loopback
HTTP server, asserting the probe's nonce arrives in the OTLP protobuf body —
that is the export path the docs claim, minus only the hosting.
"""

from __future__ import annotations

import importlib.util
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "examples" / "observability" / "verify_otlp.py"

_spec = importlib.util.spec_from_file_location("verify_otlp", _SCRIPT)
verify_otlp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_otlp)


def _jaeger_payload(*, with_nonce: str | None = None, service: str = "mcp-toolkit-demo"):
    tags = [{"key": "workflow.name", "value": "agentic_rag.query"}]
    if with_nonce:
        tags.append({"key": "verify.nonce", "value": with_nonce})
    return {
        "data": [
            {
                "traceID": "abc123",
                "spans": [
                    {
                        "spanID": "def456",
                        "operationName": "otlp_verify.probe",
                        "tags": tags,
                        "process": {"serviceName": service},
                    }
                ],
            }
        ]
    }


def _client(payload):
    return httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )


def test_check_passes_when_probe_trace_arrives():
    with _client(_jaeger_payload(with_nonce="cafebabe")) as client:
        result = verify_otlp.check_backend(
            "http://jaeger.test", "mcp-toolkit-demo", nonce="cafebabe", client=client
        )
    assert result["ok"] is True
    assert result["mode"] == "nonce"
    assert result["trace_ids"] == ["abc123"]
    assert result["sample_tags"]["workflow.name"] == "agentic_rag.query"


def test_check_fails_when_backend_holds_no_traces():
    with _client({"data": []}) as client:
        result = verify_otlp.check_backend(
            "http://jaeger.test", "mcp-toolkit-demo", nonce="cafebabe", client=client
        )
    assert result["ok"] is False
    assert result["traces_found"] == 0


def test_check_rejects_someone_elses_trace():
    # The backend answers with traces, but none carries our nonce.
    with _client(_jaeger_payload(with_nonce="not-ours")) as client:
        result = verify_otlp.check_backend(
            "http://jaeger.test", "mcp-toolkit-demo", nonce="cafebabe", client=client
        )
    assert result["ok"] is False
    assert result["traces_found"] == 1


def test_check_without_nonce_accepts_any_service_trace():
    with _client(_jaeger_payload()) as client:
        result = verify_otlp.check_backend(
            "http://jaeger.test", "mcp-toolkit-demo", client=client
        )
    assert result["ok"] is True
    assert result["mode"] == "any-trace"


def test_query_request_shape():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        verify_otlp.query_traces(
            "http://jaeger.test/", "svc", nonce="abc", client=client
        )
    request = seen[0]
    assert request.url.path == "/api/traces"
    assert request.url.params["service"] == "svc"
    assert request.url.params["tag"] == "verify.nonce:abc"


def test_artifact_is_dated_and_never_leaks_otlp_headers(monkeypatch, tmp_path):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "api-key=supersecrettoken")
    result = {
        "date": "2026-10-26T00:00:00+00:00",
        "ok": True,
        "otlp_headers_configured": True,
    }
    out = verify_otlp.write_artifact(result, tmp_path / "proof.json")
    text = out.read_text()
    assert "supersecrettoken" not in text
    assert json.loads(text)["otlp_headers_configured"] is True


def test_emit_probe_reaches_otlp_endpoint_over_http(monkeypatch):
    received: list[bytes] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            received.append(self.rfile.read(length))
            # A clean, framed 200: anything ambiguous here makes the exporter
            # treat the send as failed and retry the batch.
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", f"http://127.0.0.1:{port}")
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT_OVERRIDE", raising=False)
        monkeypatch.setenv("OTEL_BSP_SCHEDULE_DELAY", "100")
        emit = verify_otlp.emit_probe("mcp-toolkit-demo")
        nonce = emit["nonce"]
        deadline = time.monotonic() + 10
        while not received and time.monotonic() < deadline:
            time.sleep(0.05)
        # Deliberately no server.shutdown(): the OTel SDK flushes again at
        # interpreter exit, and a dead stub makes that flush retry and log
        # errors. The daemon thread dies with the process; until then the sink
        # keeps accepting whatever the SDK sends.
        time.sleep(0.2)
    finally:
        assert received, "no OTLP POST reached the collector stub"

    assert emit["spans_recorded"] == 1
    assert nonce.encode() in b"".join(received)


def test_emit_refuses_without_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT_OVERRIDE", raising=False)
    try:
        verify_otlp.emit_probe("mcp-toolkit-demo")
    except SystemExit as exc:
        assert "OTEL_EXPORTER_OTLP_ENDPOINT" in str(exc)
    else:
        raise AssertionError("emit_probe should refuse without an ingest endpoint")
