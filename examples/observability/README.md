# Observability Demo

OTel spans from the toolkit's telemetry APIs, exported to a local Jaeger.
`render.yaml` also defines a Render blueprint with a 15-minute seeder cron.
That deployment has not been verified, and no public URL is maintained.

## What you see

The seeder sets these attributes. Token counts, latency and cache state are
sampled from ranges in `seed_traces.py`, not measured:

| Attribute | Source |
|---|---|
| `workflow.name` | Workflow span name from `WORKFLOWS` (e.g. `agentic_rag.query`) |
| `workflow.cache_hit` | Sampled with probability 0.42; no cache is queried |
| `llm.provider` / `llm.model` | Label declared per workflow in `WORKFLOWS`; no model is called |
| `llm.input_tokens` / `llm.output_tokens` | Sampled from the `WORKFLOWS` ranges |
| `llm.cost_usd` | Computed via `CostTracker` against `mcp_toolkit/pricing/2026.json` |
| `tool.name` / `tool.duration_ms` | Per-tool spans (separate traces, not children of the workflow span) |
| `tool.cost_usd_partial` | Workflow cost divided evenly across its tool chain |

The seeder calls the framework's `TelemetryProvider.span()`,
`TelemetryProvider.record_tool_call()` and `CostTracker.record_usage()` APIs.

## Local — Docker Compose

```bash
docker compose up -d                                   # start Jaeger
pip install -e '../..[telemetry]'                     # source install; PyPI is stale
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
    python demo.py                                     # 3 sample spans
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
    python seed_traces.py                              # 8-14 sampled workflows
open http://localhost:16686                            # browse traces
```

## Render blueprint (config only, deployment unverified)

`render.yaml` defines two services:

1. **`mcp-toolkit-jaeger`** — Jaeger all-in-one web service (free plan)
2. **`mcp-toolkit-trace-seeder`** — cron that runs `seed_traces.py` every 15 min
   over Render's private network

Deploy:

```bash
# 1. Push this repo to GitHub
# 2. Open https://dashboard.render.com/blueprints/new
# 3. Connect the repo and select examples/observability/render.yaml
# 4. Render provisions both services in ~3 min
```

After deploy:

- Jaeger UI: the URL Render assigns to `mcp-toolkit-jaeger`
- Cron logs: Render dashboard → mcp-toolkit-trace-seeder → Logs
- Internal OTLP ingest: `http://mcp-toolkit-jaeger:4318` (cron only)

## Scope

This example shows the span attributes the telemetry APIs can carry: cost,
cache state, tokens and tool names. The values are sampled, the tool spans are
separate traces rather than children of the workflow span, and nothing here
measures a production system.
