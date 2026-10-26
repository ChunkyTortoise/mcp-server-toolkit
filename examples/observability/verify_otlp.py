"""Verify OTLP export from TelemetryProvider end to end, and record a dated artifact.

This is the verification half of the observability proof-of-life (the deploy steps
are in README.md next to this file). It closes the loop the docs claim but do not
prove: real spans leave the toolkit over OTLP HTTP and are retrievable from a
trace backend's query API.

Two halves, usable together or apart:

  --emit   run one probe span through the real OTel SDK exporter (needs an OTLP
           ingest endpoint in OTEL_EXPORTER_OTLP_ENDPOINT; honors the
           OTEL_EXPORTER_OTLP_ENDPOINT_OVERRIDE used by render.yaml)
  --check  query the backend's Jaeger-compatible API for traces from the service
           (for the hosted stack the 15-minute cron provides the emit, so a
           --check from outside is the end-to-end proof)

Typical runs:

  # Full loop against local Jaeger (docker compose up -d first)
  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
      python examples/observability/verify_otlp.py --emit --check

  # Hosted stack: ingest is internal to Render; the cron exports from inside.
  # Verify from your machine against the public query URL:
  python examples/observability/verify_otlp.py --check \
      --query-url https://<your-service>.onrender.com

The run writes a dated JSON artifact (default: otlp-proof.json next to this
file). Until a hosted run's artifact is committed, the claims ledger carries
`otlp-hosted-verification` as historical. The artifact never contains OTLP
header values (API keys travel there).

Exit status: 0 when the requested checks pass, 1 otherwise. An artifact is
written either way, so a failed run is still a dated record.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from mcp_toolkit.framework.telemetry import TelemetryProvider

PROBE_SPAN = "otlp_verify.probe"
NONCE_TAG = "verify.nonce"
DEFAULT_SERVICE = "mcp-toolkit-demo"
DEFAULT_QUERY_URL = "http://localhost:16686"
DEFAULT_OUT = Path(__file__).resolve().parent / "otlp-proof.json"


def _apply_endpoint_override() -> str | None:
    """Mirror seed_traces.py: render.yaml's override wins when present."""
    override = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT_OVERRIDE")
    if override:
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = override
    return os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")


def emit_probe(service: str) -> dict[str, Any]:
    """Emit one probe span through the real OTLP exporter; return its nonce.

    The nonce lands as a span attribute so the check half can find exactly this
    run's trace among everything else the backend holds.
    """
    _apply_endpoint_override()
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        raise SystemExit(
            "--emit needs OTEL_EXPORTER_OTLP_ENDPOINT (the OTLP ingest base URL)"
        )

    nonce = uuid.uuid4().hex[:12]
    telemetry = TelemetryProvider(service)
    telemetry.initialize(use_otel=True)
    attrs = {
        NONCE_TAG: nonce,
        "verify.date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    async def _one() -> None:
        async with telemetry.span(PROBE_SPAN, attrs):
            pass

    asyncio.run(_one())

    # Best-effort flush; the poll in main() covers backend indexing lag too.
    from opentelemetry import trace

    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush(timeout_millis=5000)
    return {"nonce": nonce, "spans_recorded": len(telemetry.spans)}


def query_traces(
    query_url: str,
    service: str,
    *,
    nonce: str | None = None,
    lookback: str = "1h",
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Fetch traces for the service from a Jaeger-compatible query API."""
    owns_client = client is None
    client = client or httpx.Client(timeout=15)
    try:
        params: dict[str, str] = {"service": service, "limit": "20", "lookback": lookback}
        if nonce:
            params["tag"] = f"{NONCE_TAG}:{nonce}"
        response = client.get(f"{query_url.rstrip('/')}/api/traces", params=params)
        response.raise_for_status()
        payload = response.json()
        return list(payload.get("data") or [])
    finally:
        if owns_client:
            client.close()


def summarise_traces(
    traces: list[dict[str, Any]], nonce: str | None
) -> dict[str, Any]:
    """Turn Jaeger trace payloads into the evidence fields of the artifact."""
    trace_ids: list[str] = []
    span_count = 0
    sample_tags: dict[str, Any] = {}
    nonce_seen = False
    for trace in traces:
        trace_ids.append(str(trace.get("traceID", "")))
        for span in trace.get("spans") or []:
            span_count += 1
            for tag in span.get("tags") or []:
                key, value = tag.get("key"), tag.get("value")
                if key == NONCE_TAG and nonce and value == nonce:
                    nonce_seen = True
                if key not in sample_tags and key != NONCE_TAG:
                    sample_tags[key] = value
    return {
        "traces_found": len(traces),
        "trace_ids": trace_ids,
        "span_count": span_count,
        "sample_tags": sample_tags,
        "nonce_seen": nonce_seen,
    }


def check_backend(
    query_url: str,
    service: str,
    *,
    nonce: str | None = None,
    lookback: str = "1h",
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Query the backend and decide whether the export path is proven.

    With a nonce, the proof requires that exact probe trace. Without one (the
    hosted cron path), any recent trace from the service proves the pipeline.
    """
    traces = query_traces(
        query_url, service, nonce=nonce, lookback=lookback, client=client
    )
    summary = summarise_traces(traces, nonce)
    ok = summary["traces_found"] > 0 and (summary["nonce_seen"] if nonce else True)
    return {
        "ok": ok,
        "mode": "nonce" if nonce else "any-trace",
        "query_url": query_url,
        "service": service,
        **summary,
    }


def poll_check(
    query_url: str,
    service: str,
    *,
    nonce: str | None = None,
    lookback: str = "1h",
    timeout: float = 30,
    interval: float = 2,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Re-run check_backend until it passes or the budget runs out."""
    deadline = time.monotonic() + timeout
    result: dict[str, Any] = {}
    while True:
        result = check_backend(
            query_url, service, nonce=nonce, lookback=lookback, client=client
        )
        if result["ok"] or time.monotonic() >= deadline:
            return result
        time.sleep(interval)


def write_artifact(result: dict[str, Any], out: Path) -> Path:
    """Write the dated record. Header values never enter the artifact."""
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--emit", action="store_true", help="send a probe span over OTLP")
    parser.add_argument(
        "--check", action="store_true", help="query the backend for traces"
    )
    parser.add_argument("--query-url", default=DEFAULT_QUERY_URL)
    parser.add_argument("--service", default=DEFAULT_SERVICE)
    parser.add_argument(
        "--nonce",
        default=None,
        help="check for this nonce (omit to accept any recent trace from the service)",
    )
    parser.add_argument("--lookback", default="1h")
    parser.add_argument("--timeout", type=float, default=30, help="check poll budget")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    do_emit = args.emit or not args.check
    do_check = args.check or not args.emit

    endpoint = _apply_endpoint_override()
    result: dict[str, Any] = {
        "tool": "examples/observability/verify_otlp.py",
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": ("emit+check" if do_emit and do_check else "emit" if do_emit else "check"),
        "service": args.service,
        "ingest_endpoint": endpoint,
        "query_url": args.query_url,
        "otlp_headers_configured": bool(os.environ.get("OTEL_EXPORTER_OTLP_HEADERS")),
    }

    nonce = args.nonce
    if do_emit:
        try:
            emit = emit_probe(args.service)
        except SystemExit as exc:
            print(f"emit failed: {exc}", file=sys.stderr)
            return 1
        nonce = emit["nonce"]
        result["emit"] = emit
        print(f"emitted probe span {PROBE_SPAN} nonce={nonce}")

    if do_check:
        check = poll_check(
            args.query_url,
            args.service,
            nonce=nonce,
            lookback=args.lookback,
            timeout=args.timeout,
        )
        result["check"] = check
        print(
            f"backend {args.query_url}: {check['traces_found']} trace(s), "
            f"{check['span_count']} span(s), ok={check['ok']}"
        )

    result["nonce"] = nonce
    check_ok = result.get("check", {}).get("ok", True)
    result["ok"] = check_ok and ("emit" not in result or bool(result["emit"]))
    write_artifact(result, args.out)
    print(f"artifact: {args.out}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
