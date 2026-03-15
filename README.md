# MCP Server Toolkit

![PyPI](https://img.shields.io/pypi/v/mcp-server-toolkit)
![Downloads](https://img.shields.io/pypi/dm/mcp-server-toolkit)

Production-ready framework for building [Model Context Protocol](https://modelcontextprotocol.io/) servers in Python. Ships with 8 pre-built servers, automatic caching, rate limiting, and OpenTelemetry integration -- so you can focus on your tool logic instead of infrastructure.

## Why?

The MCP spec gives you a protocol. This toolkit gives you the production layer on top: response caching, per-caller rate limiting, telemetry, auth, and a test client. It also includes 8 ready-to-use servers for common AI-agent tasks (database queries, web scraping, file processing, analytics, email, calendar, CRM/GoHighLevel, and vector embeddings).

## Installation

```bash
pip install mcp-server-toolkit          # Core framework only
pip install mcp-server-toolkit[database] # + Database Query server (sqlglot, asyncpg)
pip install mcp-server-toolkit[web]      # + Web Scraping server (beautifulsoup4, lxml)
pip install mcp-server-toolkit[files]    # + File Processing server (PyPDF2, openpyxl)
pip install mcp-server-toolkit[redis]    # + Redis-backed caching
pip install mcp-server-toolkit[telemetry]# + OpenTelemetry tracing
pip install mcp-server-toolkit[all]      # Everything
```

## Quick Start

```python
from mcp_toolkit import EnhancedMCP

mcp = EnhancedMCP("my-server")

@mcp.tool()
async def greet(name: str) -> str:
    """Greet a user by name."""
    return f"Hello, {name}!"

@mcp.cached_tool(ttl=300)
async def expensive_query(query: str) -> str:
    """Results cached for 5 minutes automatically."""
    return await run_query(query)

@mcp.rate_limited_tool(max_calls=10, window_seconds=60)
async def limited_action(action: str) -> str:
    """Max 10 calls per minute per caller."""
    return await perform_action(action)
```

## Pre-Built Servers

| Server | Description | Install Extra |
|--------|-------------|---------------|
| `database_query` | Natural language to SQL with sqlglot validation and schema introspection | `[database]` |
| `web_scraping` | Agent-driven web scraping with structured data extraction | `[web]` |
| `file_processing` | PDF/CSV/Excel/TXT parsing with RAG-optimized chunking | `[files]` |
| `analytics` | Metrics recording, aggregation, anomaly detection (z-score), chart generation | core |
| `email` | Email composition with template engine | core |
| `calendar` | Availability checking and scheduling | core |
| `crm_ghl` | GoHighLevel CRM — contact CRUD, pipeline summaries, opportunity tracking with field mapping | core |
| `gemini_embedding` | Gemini Embedding 2 — text embedding, semantic search, vector indexing, cosine similarity | core |

### Database Query Server

```python
from mcp_toolkit.servers.database_query.server import mcp, configure

# Connect to your database
configure(db_connection=my_async_db, dialect="postgres")

# Tools available to agents:
# - query_database("How many users signed up last week?")
# - explain_query("Show me top customers by revenue")
# - list_tables()
```

### Analytics Server

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

### Web Scraping Server

```python
from mcp_toolkit.servers.web_scraping.server import mcp

# Tools available:
# - scrape_page(url="https://example.com", extract="product prices")
# - extract_structured(url="...", schema={"name": "str", "price": "float"})
```

### CRM GoHighLevel Server

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

### Gemini Embedding Server

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

### Claude Desktop Configuration

Add servers to `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "analytics": {
      "command": "python3",
      "args": ["-m", "mcp_toolkit.servers.analytics.server"]
    },
    "crm-ghl": {
      "command": "python3",
      "args": ["-m", "mcp_toolkit.servers.crm_ghl.server"]
    },
    "gemini-embedding": {
      "command": "python3",
      "args": ["-m", "mcp_toolkit.servers.gemini_embedding.server"],
      "env": {
        "GEMINI_API_KEY": "your-api-key"
      }
    }
  }
}
```

## Framework Features

### Caching

Built-in L1 (in-memory) cache with optional Redis backend:

```python
from mcp_toolkit.framework.caching import CacheLayer, RedisCache

# Redis-backed caching
cache = CacheLayer(backend=RedisCache(url="redis://localhost:6379"))
```

### Rate Limiting

Per-caller rate limiting with configurable windows:

```python
@mcp.rate_limited_tool(max_calls=100, window_seconds=60)
async def my_tool(query: str) -> str:
    ...
```

### Authentication

API key and OAuth support:

```python
from mcp_toolkit.framework.auth import APIKeyAuth, OAuthAuth

auth = APIKeyAuth()
auth.add_key("my-api-key", scopes=["read", "write"])
```

### Telemetry

OpenTelemetry integration for tracing and metrics:

```python
from mcp_toolkit.framework.telemetry import TelemetryProvider

telemetry = TelemetryProvider("my-server")
telemetry.initialize()
```

### Testing

First-class test client for unit testing your MCP servers:

```python
from mcp_toolkit import MCPTestClient

client = MCPTestClient(mcp)
result = await client.call_tool("greet", {"name": "World"})
assert result == "Hello, World!"
```

## Examples

See the [`examples/`](examples/) directory for working implementations:

- [`basic_server.py`](examples/basic_server.py) — minimal server with 2 tools
- [`cached_tools.py`](examples/cached_tools.py) — caching with `@mcp.cached_tool()` decorator
- [`database_query_usage.py`](examples/database_query_usage.py) — pre-built SQL database server
- [`crm_ghl_usage.py`](examples/crm_ghl_usage.py) — GoHighLevel CRM contact and pipeline management
- [`gemini_embedding_usage.py`](examples/gemini_embedding_usage.py) — text embedding, vector indexing, and semantic search

## Development

```bash
git clone https://github.com/ChunkyTortoise/mcp-server-toolkit.git
cd mcp-server-toolkit
pip install -e ".[dev]"
pytest tests/ -v
ruff check .
```

## License

MIT
