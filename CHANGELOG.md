# Changelog

All notable changes to mcp-server-toolkit are documented here.

## [Unreleased]

## [0.4.0] - 2026-10-24

### Breaking Changes

- Requires `mcp>=2.3,<3`; mcp 1.x is no longer supported. `EnhancedMCP` now extends `mcp.server.mcpserver.MCPServer` (FastMCP's 2.x name), and the toolkit's `Unauthorized`, `Forbidden` and `RateLimited` subclass `mcp.server.mcpserver.exceptions.ToolError`. Transport options such as `host`, `port` and `json_response` are no longer constructor arguments: pass them to `run()` or `streamable_http_app()`. The gateway keeps its JSON responses through `mcp_toolkit.gateway.app.HTTP_OPTIONS`.
- mcp 2.x reports any tool exception that is not a `ToolError` to the client as `Error executing tool <name>`, without the original message. Raise `ToolError` (or a toolkit subclass) for failures the caller should read.
- `MCPTestClient` takes an `MCPServer` and drives `call_tool_result` through `mcp.Client` (2.x removed `mcp.shared.memory.create_connected_server_and_client_session`). Results and SDK models use snake_case attributes, for example `result.is_error`, `result.structured_content`, `tool.input_schema` and `annotations.read_only_hint`; `MCPTestClient.list_tools()` still returns the wire key `inputSchema`.
- Under mcp 2.x every pre-built server negotiates protocol `2026-07-28` and advertises `listChanged: true` for tools, prompts and resources and `resources.subscribe: true` (1.x advertised `false` plus an empty `experimental` block). The servers still expose no prompts, resources or resource templates; `tests/test_capability_snapshot.py` pins both the capability object and the empty lists.

### Security

- HTTP gateway on mcp 2.x: per-tool scope checks read the bearer token of the request that carried the tool call. 2.x removed `mcp.server.lowlevel.server.request_ctx`, which `get_request_access_token` used under 1.x; 2.x runs each call in its own request's auth context instead. The regression test (a session opened with one token, a later call sent with another) now runs in both JSON and SSE response modes. The gateway sets `AuthSettings.validate_token_resource=True` as a config guard: `JWTTokenVerifier` checks `aud` and reports the configured audience as the token's resource, so the SDK check refuses every token if that audience and `resource_server_url` ever differ; it is not a second check of the token itself. The `cached_tool` refusal and verified-subject rate-limit tests also run in both response modes. A new test pins the loopback DNS-rebinding guard: a foreign `Host` header gets 421 before dispatch.
- Web scraping: a redirect could reach private and cloud-metadata addresses, because only the first URL was checked and httpx followed redirects. The scraper now follows up to 5 redirects itself, validates every hop (robots.txt included), connects to the IP it validated with the original Host header and TLS SNI, and treats any non-global address as forbidden. This holds for a caller-supplied client built with `follow_redirects=True`, and, as httpx does, the client's Authorization and Cookie headers are dropped once a hop leaves the original origin. Deprecated site-local IPv6 (`fec0::/10`), which Python reports as global, is also refused.

### Changed

- The streamable HTTP app moved from `examples/http_server.py` into `mcp_toolkit/gateway/` and ships in the wheel as the `mcp-toolkit-gateway` command (also `python -m mcp_toolkit.gateway`). `examples/http_server.py` is now a thin launcher.
- MCP SDK internals used by the gateway and `framework.http_auth` are imported only from `mcp_toolkit/gateway/sdk_bridge.py`; `tests/test_gateway/test_sdk_bridge.py` pins that surface and fails if another module imports it directly.
- `evals/quality/runner.py` prints the results markdown to stdout and no longer rewrites `evals/RESULTS.md` on every run. Pass `--write-results [PATH]` (default `evals/RESULTS.md`) to write a file; `--output PATH` still works as an alias. The nightly workflow passes the flag, and the claims ledger now executes the runner (`recovery-quality-evals`).

### Added

- `[console]` extra (`jinja2`) for the upcoming server-rendered console.

## [0.3.0] - 2026-04-26

### Breaking Changes

- `OAuthAuth` is now a **deprecated test-only stub**. Replace with `JWTAuth` (see Migration below).
- `RedisCache` now **raises on connection errors by default** (was silent fallback). Pass `fallback_to_memory=True` to restore old behavior.
- `RateLimiter` `caller_id` falls back to `"default"` with a warning log instead of silently applying global limits.

### Added

**Auth (W2):** `JWTAuth` (HS256/RS256/JWKS, audience+issuer verify, scope-based RBAC), `requires_scope` decorator, audit log sink.

**Telemetry (W1):** Full OTel rewrite, real spans via `BatchSpanProcessor`, OTLP HTTP exporter, env-var config (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`). Fixed hardcoded `0.1ms` cache-hit duration.

**Cost Attribution (W3):** `CostTracker` reads token counts from Anthropic/OpenAI/Gemini/xAI responses; `mcp_toolkit/pricing/2026.json` price table.

**A2A Bridge (W4):** `stream_task()` SSE generator (`submitted → working → completed`); `handle_task(webhook_url=…)` push notifications; agent card `pushNotifications: true` flag.

**Production Backends (W5):** `SMTPEmailClient` (stdlib), `GmailEmailClient` (`[gmail]`), `GoogleCalendarProvider` (`[gcal]`), `PostgresClient` with sqlglot read-only enforcement + pgvector `vector_search()` (`[database]`).

**Evals + Safety (W3):** 10-task quality eval suite (LLM-as-judge, nightly CI), 30-case adversarial corpus, Five Gates test suite (`tests/gates/`).

**Examples:** `a2a_bridge/`, `agentic_rag/`, `claude_desktop_app/`, `multi_agent_research/`, `observability/`.

**ADRs:** 0005 (rate-limit distribution), 0006 (OAuth 2.1), 0007 (MCP↔A2A boundary).

### Changed

- Test count: 412 → 598.
- New extras: `[auth]`, `[gmail]`, `[gcal]`.

### Migration from 0.2.0

```python
# OAuthAuth → JWTAuth
from mcp_toolkit import JWTAuth
auth = JWTAuth(secret="my-32-byte-or-longer-secret-here")

# RedisCache fallback is now opt-in
from mcp_toolkit.framework.caching import RedisCache
cache = RedisCache(fallback_to_memory=True)  # dev only
```

## [0.2.0] - 2026-03-18

### Added
- **Multi-LLM router server** (`multi_llm`): route prompts to Gemini, OpenAI, and xAI/Grok with cost-based routing, circuit breakers, and `get_second_opinion` parallel queries. Now documented in README with full usage example.
- **A2A protocol adapter** (`A2AAdapter`): bridges MCP servers to Google's Agent-to-Agent protocol for multi-vendor agent interoperability. Now documented in README with usage example.
- CI badge and coverage badge in README
- `examples/multi_llm_router.py`: working example for multi-LLM router server

### Fixed
- `auth.add_key(...)` example in README corrected to `auth.register_key(api_key, client_id, scopes)`
- `DataExtractor` no longer uses `"raw" in dir()` sentinel pattern; uses explicit `raw = ""` initialization instead
- `caller_id` in `rate_limited_tool` now checks kwargs for common identifier fields before falling back to `"default"`

### Changed
- Ruff config tightened: removed global `F841` and `F401` ignores; test-specific relaxation narrowed to only `F401` and unused variable rules
- Fixed unused import in `chart_generator.py` (`matplotlib` availability check now uses `importlib.util.find_spec`)
- 412 tests (up from 387)

### Documentation
- README: updated server count from 8 to 9 throughout
- README: added `multi_llm` to pre-built servers table
- README: added Multi-LLM Router Server usage section
- README: added A2A Protocol Support section
- CLAUDE.md: updated test count (233 → 420+) and server count (8 → 9)

## [0.1.0] - 2026-03-05

### Added
- Initial PyPI release
- 8 pre-built MCP servers: `DatabaseServer`, `WebServer`, `FileServer`, `AnalyticsServer`, `EmailServer`, `CalendarServer`, `CrmGhlServer`, `GeminiEmbeddingServer`
- `@mcp.tool()` decorator for simple tool registration
- `@mcp.cached_tool()` decorator with configurable TTL
- `@mcp.rate_limited_tool()` decorator with per-caller limits
- `EnhancedMCP` base class extending FastMCP with `run()` entrypoint
- `MCPTestClient` for unit testing MCP servers
- Full async support via `asyncio`
- Pydantic v2 input/output validation
- 233 tests with 100% core coverage

### Servers
- **DatabaseServer**: query any SQL database (PostgreSQL, MySQL, SQLite)
- **WebServer**: HTTP fetch, scraping, and link extraction
- **FileServer**: read/write/search local files safely
- **AnalyticsServer**: data aggregation and statistics tools
- **EmailServer**: SMTP send + IMAP read tools
- **CalendarServer**: iCal read/write tools
- **CrmGhlServer**: GoHighLevel CRM integration tools
- **GeminiEmbeddingServer**: Gemini-powered embedding and vector search tools
