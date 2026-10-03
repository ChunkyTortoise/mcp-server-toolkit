# RAG example and synthetic trace walkthrough

The local [Streamlit example](../examples/agentic_rag/app.py) runs a fixed
embed, retrieve, synthesize sequence. The separate
[trace seeder](../examples/observability/seed_traces.py) emits synthetic workflow
spans through the toolkit's telemetry and cost APIs. These are two examples,
not a measured production deployment. This documentation builds on the
verified walkthrough in [PR #44](https://github.com/ChunkyTortoise/mcp-server-toolkit/pull/44),
base `b4b53fe`. It describes that branch's source-count controls and explicit
service-failure behavior.

## What the Python example does

1. `embed_query` returns a deterministic fake 128-dimensional vector.
2. Without `PGVECTOR_URL`, `retrieve_chunks` returns seeded chunks in a fixed
   score order. Changing the query does not change the ranking.
3. Without `ANTHROPIC_API_KEY`, `synthesize` returns a template answer with
   source markers. These markers show formatting, not evaluated faithfulness.

The source-count slider controls `top_k` (default four). The fixture has five
chunks, so selecting six through eight still returns at most five seeded
sources. Configured retrieval may return up to the requested count.
The example has no agent decision loop, rerank step, MCP tool registration,
cache decorator, auth wrapper, or telemetry wrapper.

```bash
# After a source install and a separate Streamlit install:
streamlit run examples/agentic_rag/app.py
```

The host can configure service attempts: Anthropic synthesis needs the
`anthropic` package; pgvector retrieval needs `asyncpg`, a prepared `documents`
table, and compatible stored vectors. The query embedding remains fake.
Configured retrieval or synthesis errors raise a `RuntimeError`, which the UI
displays; they do not silently turn into fixture success. Empty retrieval
returns "No sources found. No answer was generated." Configuration labels
do not prove successful backend execution. No live API or database path was
verified in this audit.

## What the trace seeder demonstrates

The seeder calls `TelemetryProvider.span()` and `CostTracker.record_usage()`.
It samples token counts and delays from ranges in `WORKFLOWS`, samples a
cache-hit boolean with probability 0.42, and sleeps to illustrate stage timing.
It does not execute retrieval, synthesis, SQL, SMTP, or an embedding API.
The 0.42 probability is an input, not an observed cache-hit rate.

A trace can therefore show workflow names, child spans, sampled tokens,
calculated cost, and simulated cache state. Cost uses the repository's
[dated pricing table](../mcp_toolkit/pricing/2026.json); it is not a bill from
a live API call. Latency is simulated, not a benchmark of service performance.

```bash
cd examples/observability
docker compose up -d
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 python seed_traces.py
# Open http://localhost:16686 and filter by service mcp-toolkit-demo
```

The [trace screenshot](../assets/jaeger-trace-demo.png) and
[HTML illustration](../assets/jaeger-trace-preview.html) are static artifacts.
A [Render blueprint](../examples/observability/render.yaml) is committed;
this walkthrough does not establish a deployed dashboard.

## Evidence boundaries

| Evidence | What it supports | What it does not establish |
|---|---|---|
| [Cache benchmark](../benchmarks/RESULTS.md), April 25, 2026 | Local framework cache timings from that dated run | End-to-end RAG latency or a production hit rate |
| [Python example](../examples/agentic_rag/app.py), base `b4b53fe` | Source code for fake embeddings, fixed ranking and template output | Retrieval relevance or live-provider success |
| [Telemetry implementation](../mcp_toolkit/framework/telemetry.py) | Toolkit span and exporter code | App instrumentation or a deployed service |
| [Cost implementation](../mcp_toolkit/framework/costing.py) | Cost calculation from supplied usage and dated rates | Current provider pricing or paid usage in this demo |

The earlier production P95, 500-query load, cache-hit, monthly cost and
scale projections had no reproducible load-test receipt in this tree.
They have been removed from this walkthrough. A production claim would need
actual service configuration, measured requests and a dated receipt.
