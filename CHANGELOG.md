# Changelog

All notable changes to mcp-server-toolkit are documented here.

## [0.1.0] — 2026-03-05

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
- **DatabaseServer** — query any SQL database (PostgreSQL, MySQL, SQLite)
- **WebServer** — HTTP fetch, scraping, and link extraction
- **FileServer** — read/write/search local files safely
- **AnalyticsServer** — data aggregation and statistics tools
- **EmailServer** — SMTP send + IMAP read tools
- **CalendarServer** — iCal read/write tools
- **CrmGhlServer** — GoHighLevel CRM integration tools
- **GeminiEmbeddingServer** — Gemini-powered embedding and vector search tools
