# Examples and usage reference

Runnable examples live in this directory. Run every command below from the repository root after the [source install](../README.md#quickstart). The sections below were moved here from the top-level README unchanged apart from link paths; the [Methodology & limits](../README.md#methodology--limits) section of the README covers what each demo does and does not show.

## Example index

Working implementations in this directory:

- [`basic_server.py`](basic_server.py): minimal server with 2 tools
- [`cached_tools.py`](cached_tools.py): caching with `@mcp.cached_tool()`
- [`database_query_usage.py`](database_query_usage.py): pre-built SQL database server
- [`crm_ghl_usage.py`](crm_ghl_usage.py): GoHighLevel CRM contact and pipeline management
- [`gemini_embedding_usage.py`](gemini_embedding_usage.py): embedding, vector indexing, semantic search
- [`a2a_bridge/`](a2a_bridge/): A2A bridge, Starlette server + client, SSE streaming, webhooks
- [`agentic_rag/`](agentic_rag/): Streamlit RAG app, query embedding to pgvector to cited synthesis
- [`claude_desktop_app/`](claude_desktop_app/): one-command Claude Desktop setup wiring 3 servers
- [`multi_agent_research/`](multi_agent_research/): orchestrator, parallel web search + multi-LLM synthesis + A2A output
- [`observability/`](observability/): Jaeger docker-compose + OTel span demo

## Seeded RAG walkthrough

This optional example uses deterministic demo vectors, fixed ranked sources and a template answer. The Python UI is a standalone pipeline example, not MCP tool dispatch. The HTML preview is an illustration; it does not run Python, retrieve documents or call a model.

| Open | What to expect |
|---|---|
| [Walkthrough GIF](../assets/agentic-rag-demo.gif) | Earlier fixture demonstration, optional motion |
| [HTML source, download then open](../assets/agentic-rag-demo-preview.html) | GitHub displays source; use Download raw file, then open the saved HTML in your browser |
| `streamlit run examples/agentic_rag/app.py` | Optional Streamlit 1.64+ required for tracked expanders; seeded mode needs no keys |

For a rendered preview from a local checkout, no package installation is needed:

```bash
python -m http.server 8613 --bind 127.0.0.1 --directory assets
```

Open http://127.0.0.1:8613/agentic-rag-demo-preview.html. The downloaded HTML also works offline with `file://`. Both illustrations use the five sources in `examples/agentic_rag/fixtures.json`; regenerate the embedded HTML data with `python examples/agentic_rag/build_preview.py` after editing them. Source summaries are complete, cited, and independent of the question.

Configured synthesis and retrieval require separate dependencies and services. Retrieval still uses deterministic demo vectors, so it is not a verified semantic-search integration. Provider failures are shown explicitly instead of silently becoming fixture success.

## Local demos (no hosted dependency)

| What | How | What you see |
|---|---|---|
| OTel + Jaeger traces | `cd examples/observability && docker compose up -d && python seed_traces.py` | Spans carrying `cost_usd`, `cache_hit`, `tokens_in/out` ([`seed_traces.py`](observability/seed_traces.py)). [Screenshot preview](../assets/jaeger-trace-demo.png) from real `TelemetryProvider` spans. Render blueprint committed but not yet deployed ([`render.yaml`](observability/render.yaml)). |
| Agentic RAG app | [`examples/agentic_rag/app.py`](agentic_rag/app.py) | Standalone seeded pipeline; optional configured services, not MCP tool calls |
| Worked case study | [`docs/CASE_STUDY.md`](../docs/CASE_STUDY.md) | Synthetic trace walkthrough with explicit limits; no production latency or hit-rate measurement |

**Observability preview (secondary; no deploy required):** open [`assets/jaeger-trace-preview.html`](../assets/jaeger-trace-preview.html) for a static Jaeger-style cost/cache span view. The actual cache receipt in the top-level README is the first-screen evidence; this HTML preview is a secondary local artifact, not a hosted dashboard.

## Pre-built servers

Nine servers, import and run, no boilerplate.

| Server | Description | Install extra |
|--------|-------------|---------------|
| `database_query` | Natural language to SQL with sqlglot validation and schema introspection | `[database]` |
| `web_scraping` | Agent-driven web scraping with structured data extraction | `[web]` |
| `file_processing` | PDF/CSV/Excel/TXT parsing with RAG-optimized chunking | `[files]` |
| `analytics` | Metrics recording, aggregation, anomaly detection (z-score), chart generation | core |
| `email` | Email composition with template engine | core |
| `calendar` | Availability checking and scheduling | core |
| `crm_ghl` | GoHighLevel CRM: contact CRUD, pipeline summaries, opportunity tracking with field mapping | core |
| `gemini_embedding` | Gemini Embedding 2: text embedding, semantic search, vector indexing, cosine similarity | core |
| `multi_llm` | Multi-provider LLM router: Gemini/OpenAI/xAI with cost routing, circuit breakers, parallel second opinions | core |

<details>
<summary><strong>database_query</strong>: Natural language to SQL with sqlglot validation and schema introspection</summary>

```python
from mcp_toolkit.servers.database_query.server import mcp, configure

# Connect to your database
configure(db_connection=my_async_db, dialect="postgres")

# Tools available to agents:
# - query_database("How many users signed up last week?")
# - explain_query("Show me top customers by revenue")
# - list_tables()
```

</details>

<details>
<summary><strong>analytics</strong>: Metrics recording, aggregation, anomaly detection, chart generation</summary>

```python
from mcp_toolkit.servers.analytics.server import mcp, configure, MetricsStore

store = MetricsStore()
store.record("response_time", 145.2, timestamp="2024-01-15T10:00:00Z")
configure(store=store)

# Tools available:
# - query_metrics(metric="response_time", aggregation="avg")
# - detect_anomalies(metric="error_rate", z_threshold=2.0)
# - generate_chart(metric="response_time", chart_type="line")
```

</details>

<details>
<summary><strong>web_scraping</strong>: Agent-driven web scraping with structured data extraction</summary>

```python
from mcp_toolkit.servers.web_scraping.server import mcp

# Tools available:
# - scrape_page(url="https://example.com", extract="product prices")
# - extract_structured(url="...", schema={"name": "str", "price": "float"})
```

</details>

<details>
<summary><strong>crm_ghl</strong>: GoHighLevel CRM contact management, pipeline tracking, and opportunity creation</summary>

Contact management, pipeline tracking, and opportunity creation for GoHighLevel CRM. Includes a `GHLFieldMapper` for resolving natural language field names to GHL custom field IDs. Falls back to a `MockGHLClient` when no real client is configured, so agents can demo the tools without API credentials.

```python
from mcp_toolkit.servers.crm_ghl.server import mcp, configure

# Use the mock client for demos (default), or provide your own GHL API client
# configure(client=my_ghl_client)

# Tools available to agents:
# - search_contacts("John", limit=10)
# - create_contact(first_name="John", last_name="Doe", email="john@example.com")
# - get_pipeline_summary(pipeline_id="")
# - create_opportunity(contact_id="c1", name="Website Redesign", value=5000)
```

</details>

<details>
<summary><strong>gemini_embedding</strong>: Semantic search and vector indexing powered by Gemini Embedding 2</summary>

Semantic search and vector indexing powered by Gemini Embedding 2. Embeds text, indexes documents into an in-memory vector store, and performs cosine-similarity search. Uses a deterministic `MockEmbeddingClient` by default so agents can test without a Gemini API key.

```python
from mcp_toolkit.servers.gemini_embedding.server import mcp, configure

# Set GEMINI_API_KEY env var for real embeddings, or use the mock client (default)
# Tools available:
# - embed_text("hello world", task_type="SEMANTIC_SIMILARITY")
# - index_text(text="document content", item_id="doc1", metadata='{"source": "readme"}')
# - search(query="async patterns", top_k=5)
# - similarity(text_a="Python", text_b="JavaScript")
# - list_indexed()
# - clear_index()
```

</details>

<details>
<summary><strong>multi_llm</strong>: Multi-provider LLM router with cost routing, circuit breakers, and parallel second opinions</summary>

Route prompts across Gemini, OpenAI, and xAI/Grok based on cost or quality. Includes per-provider circuit breakers, parallel second-opinion queries, and automatic fallback.

```python
from mcp_toolkit.servers.multi_llm.server import mcp, configure
from mcp_toolkit.servers.multi_llm.providers import GeminiProvider, OpenAICompatibleProvider
from mcp_toolkit.servers.multi_llm.models import ProviderName

configure(providers={
    ProviderName.GEMINI: GeminiProvider(api_key="...", default_model="gemini-2.5-pro"),
    ProviderName.OPENAI: OpenAICompatibleProvider(
        api_key="...", base_url="https://api.openai.com/v1",
        provider=ProviderName.OPENAI, default_model="gpt-5.5",
    ),
})

# Tools available to agents:
# - query_model(provider="gemini", model="gemini-2.5-pro", prompt="...")
# - query_cheap(prompt="...")          # routes to cheapest available model
# - query_best(prompt="...")           # routes to highest-quality available model
# - get_second_opinion(prompt="...")   # queries all providers in parallel
# - list_providers()                   # shows status and circuit breaker state
```

Set `GEMINI_API_KEY`, `OPENAI_API_KEY`, and/or `XAI_API_KEY` to enable each provider. Providers without a key are skipped; `query_cheap` and `query_best` fall through to the next available option automatically.

</details>

<details>
<summary><strong>email</strong>: Email composition with template engine</summary>

```python
from mcp_toolkit.servers.email.server import mcp

# Tools available to agents for email composition and templating
```

</details>

<details>
<summary><strong>calendar</strong>: Availability checking and scheduling</summary>

```python
from mcp_toolkit.servers.calendar.server import mcp

# Tools available to agents for availability checking and scheduling
```

</details>

<details>
<summary><strong>file_processing</strong>: PDF/CSV/Excel/TXT parsing with RAG-optimized chunking</summary>

```python
from mcp_toolkit.servers.file_processing.server import mcp

# Tools available:
# - parse_file(path="report.pdf")
# - chunk_for_rag(text="...", chunk_size=512)
```

</details>

## Framework features

### Caching

Built-in L1 (in-memory) cache with optional Redis backend:

```python
from mcp_toolkit.framework.caching import CacheLayer, RedisCache

cache = CacheLayer(backend=RedisCache(url="redis://localhost:6379"))
```

Redis fallback is opt-in, not silent: `fallback_to_memory=False` is the default and a typed `_REDIS_TRANSIENT` exception signals a recoverable failure.

### Rate limiting

Per-caller rate limiting with configurable windows:

```python
@mcp.rate_limited_tool(max_calls=100, window_seconds=60)
async def my_tool(query: str) -> str:
    ...
```

### Authentication

API key authentication with SHA-256 hashed key storage:

```python
from mcp_toolkit.framework.auth import APIKeyAuth

auth = APIKeyAuth()
auth.register_key("my-api-key", client_id="my-client", scopes=["read", "write"])
result = await auth.authenticate("my-api-key")
# AuthResult(authenticated=True, client_id="my-client", scopes=["read", "write"])
```

`JWTAuth` supports HS256 (symmetric) and RS256 via a JWKS endpoint. Add `requires_scope(auth, "db:read")` to any tool for scope-based RBAC. See [ADR-0006](../docs/adr/ADR-0006-oauth-2.1-resource-server.md).

### Telemetry

> Note: in the current code, spans are recorded automatically only by `cached_tool` and `rate_limited_tool`, the cache attribute is named `cache_hit`, and `cost_usd` appears only when you add it. See [Methodology & limits](../README.md#methodology--limits).

Tools wrapped with `cached_tool` or `rate_limited_tool` record a span automatically. Other tools are instrumented only when you call `telemetry.span()` yourself. Set up the provider:

```python
from mcp_toolkit.framework.telemetry import TelemetryProvider

telemetry = TelemetryProvider("my-server")
telemetry.initialize()                 # in-memory only (good for tests)

import os
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4318"
telemetry.initialize(use_otel=True)    # real OTel spans via OTLP (Jaeger, Grafana Cloud)
```

See [`examples/observability/`](observability/) for a Docker Compose Jaeger setup.

### Testing

Test client for unit testing your MCP servers:

```python
from mcp_toolkit import MCPTestClient

client = MCPTestClient(mcp)
result = await client.call_tool("greet", {"name": "World"})
assert result == "Hello, World!"
```

### Cost attribution

Track per-call USD cost across LLM providers using the dated, versioned pricing table in `mcp_toolkit/pricing/2026.json`:

```python
from mcp_toolkit import CostTracker

tracker = CostTracker()
cost = tracker.record_from_anthropic_usage(message.usage, model="claude-sonnet-4-6", tool_name="query_db")
cost = tracker.record_from_response_dict(response, provider="google", model="gemini-2.5-pro")

print(tracker.summary())
# {'total_cost_usd': 0.00042, 'total_calls': 3, 'by_model': {'openai/gpt-5.5': 0.00018, ...}}
```

To see cost on a trace, set it as an attribute on the span yourself; `CostTracker` does not write it to spans automatically.

### Quality evals

10-task deterministic eval suite covering routing logic, auth correctness, cost accuracy, and cache semantics. Runs in CI without API keys:

```bash
python evals/quality/runner.py           # deterministic (no API key)
python evals/quality/runner.py --judge   # + LLM-as-judge scoring (needs ANTHROPIC_API_KEY)
```

A nightly GitHub Actions workflow re-runs the suite with LLM-as-judge scoring and uploads `evals/RESULTS.md` as an artifact.

### Adversarial safety corpus

30-case injection corpus at `tests/adversarial/injection_corpus.jsonl` covering prompt injection, token forgery (`alg:none`, wrong secret, expired), scope escalation, cache poisoning, and data exfiltration. Each case documents whether the toolkit layer blocks the threat and the defence mechanism.

## A2A protocol support

Every MCP server in this toolkit can be exposed as a [Google Agent-to-Agent (A2A)](https://a2a-protocol.org/) compatible agent. The `A2AAdapter` bridges MCP tool invocations to the A2A task protocol. SSE streaming and webhook push notifications are both implemented; the agent card advertises `streaming: true` and `pushNotifications: true` when a webhook endpoint is registered.

```python
from mcp_toolkit import EnhancedMCP
from mcp_toolkit.framework.a2a_adapter import A2AAdapter

mcp = EnhancedMCP("my-server")

@mcp.tool()
async def answer(question: str) -> str:
    return f"Answer to: {question}"

adapter = A2AAdapter(mcp, base_url="https://my-server.example.com")

# Agent card auto-derived from live MCP tool schemas
agent_card = await adapter.get_agent_card()

# Synchronous task: returns final status; posts webhook callbacks on each state change
status = await adapter.handle_task(
    "task-123", "answer", {"question": "What is 2+2?"},
    webhook_url="https://caller.example.com/webhook",   # optional
)

# Streaming task: yields SSE events (submitted, working, completed)
async for sse_chunk in adapter.stream_task("task-456", "answer", {"question": "..."}):
    print(sse_chunk, end="")
```

State transitions emitted: `submitted` to `working` to `completed` or `failed`. Push notifications POST JSON to the caller's webhook on every transition; delivery failures are logged and do not affect the task result. See [`examples/a2a_bridge/`](a2a_bridge/) for a Starlette server + client demo, and [ADR-0007](../docs/adr/ADR-0007-mcp-a2a-boundary.md) for the MCP/A2A boundary design.
