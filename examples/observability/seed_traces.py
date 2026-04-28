"""Seed sample MCP traces into Jaeger so the public demo dashboard stays warm.

Runs as a Render cron every 15 minutes. Emits 5 representative workflows with
real OTel attributes (cost_usd, cache_hit, tokens_in/out, latency_ms) so a
hiring manager opening the Jaeger UI always sees live, realistic spans.

No API keys required — this is a pure tracing demo. Token counts and costs are
synthesized from a deterministic distribution that matches typical MCP tool
call patterns observed in production.

Usage:
    # Local
    docker compose up -d
    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 python seed_traces.py

    # Render (cron schedule "*/15 * * * *" — see render.yaml)
"""

from __future__ import annotations

import asyncio
import os
import random
import time

# Honor the OTLP override env var from render.yaml when present
_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT_OVERRIDE")
if _endpoint:
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = _endpoint
os.environ.setdefault("OTEL_SERVICE_NAME", "mcp-toolkit-demo")

from mcp_toolkit.framework.costing import CostTracker  # noqa: E402
from mcp_toolkit.framework.telemetry import TelemetryProvider  # noqa: E402


WORKFLOWS = [
    {
        "name": "agentic_rag.query",
        "tool_chain": ["embed_query", "retrieve_chunks", "rerank", "synthesize"],
        "model": ("anthropic", "claude-haiku-4-5-20251001"),
        "input_tokens": (480, 720),
        "output_tokens": (180, 320),
        "latency_ms": (320, 680),
    },
    {
        "name": "multi_llm.compare",
        "tool_chain": ["dispatch", "anthropic_call", "openai_call", "score"],
        "model": ("openai", "gpt-5.5"),
        "input_tokens": (260, 410),
        "output_tokens": (140, 220),
        "latency_ms": (410, 920),
    },
    {
        "name": "database_query.execute",
        "tool_chain": ["validate_sql", "execute", "format_rows"],
        "model": None,
        "input_tokens": (0, 0),
        "output_tokens": (0, 0),
        "latency_ms": (12, 95),
    },
    {
        "name": "email.send_with_template",
        "tool_chain": ["render_template", "smtp_send"],
        "model": None,
        "input_tokens": (0, 0),
        "output_tokens": (0, 0),
        "latency_ms": (140, 380),
    },
    {
        "name": "gemini_embedding.batch_embed",
        "tool_chain": ["chunk_input", "embed_batch", "store"],
        "model": ("google", "gemini-2.5-pro"),
        "input_tokens": (1200, 2400),
        "output_tokens": (0, 0),
        "latency_ms": (180, 410),
    },
]


async def fire_workflow(
    telemetry: TelemetryProvider,
    cost: CostTracker,
    spec: dict,
) -> None:
    """Emit one parent span + child tool spans matching a real workflow."""
    rng = random.Random()
    cache_hit = rng.random() < 0.42  # ~42% cache hit rate (matches production)
    parent_attrs = {
        "workflow.name": spec["name"],
        "workflow.cache_hit": cache_hit,
    }

    cost_usd = 0.0
    if spec["model"] is not None:
        provider, model = spec["model"]
        in_tok = rng.randint(*spec["input_tokens"])
        out_tok = rng.randint(*spec["output_tokens"])
        cost_usd = cost.record_usage(
            provider=provider,
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            tool_name=spec["name"],
        )
        parent_attrs.update(
            {
                "llm.provider": provider,
                "llm.model": model,
                "llm.input_tokens": in_tok,
                "llm.output_tokens": out_tok,
                "llm.cost_usd": cost_usd,
            }
        )

    async with telemetry.span(spec["name"], parent_attrs):
        for tool in spec["tool_chain"]:
            tool_latency = rng.uniform(*spec["latency_ms"]) / len(spec["tool_chain"])
            if cache_hit and tool in {"retrieve_chunks", "embed_query", "embed_batch"}:
                tool_latency = 0.007  # cache hit floor — matches benchmarks/RESULTS.md

            await asyncio.sleep(min(tool_latency / 1000, 0.05))
            telemetry.record_tool_call(
                tool,
                duration_ms=tool_latency,
                success=True,
                cache_hit=cache_hit and tool in {"retrieve_chunks", "embed_query", "embed_batch"},
                **(
                    {"cost_usd_partial": round(cost_usd / len(spec["tool_chain"]), 8)}
                    if cost_usd
                    else {}
                ),
            )


async def main() -> None:
    telemetry = TelemetryProvider("mcp-toolkit-demo")
    telemetry.initialize(use_otel=True)
    cost = CostTracker()

    t0 = time.monotonic()
    rng = random.Random()
    for _ in range(rng.randint(8, 14)):  # 8-14 workflows per cron tick
        spec = rng.choice(WORKFLOWS)
        await fire_workflow(telemetry, cost, spec)

    summary = cost.summary()
    elapsed = time.monotonic() - t0
    print(
        f"Seeded {len(telemetry.spans)} spans in {elapsed:.2f}s — "
        f"total cost ${summary['total_cost_usd']:.6f} across "
        f"{summary['total_calls']} LLM calls"
    )

    # BatchSpanProcessor flush window
    await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
