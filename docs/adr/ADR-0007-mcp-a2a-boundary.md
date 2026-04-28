# ADR-0007 — MCP ↔ A2A Boundary: When to Bridge vs. Native

**Status:** Accepted  
**Date:** 2026-04-26  
**Authors:** mcp-server-toolkit maintainers

---

## Context

The [Model Context Protocol (MCP)](https://modelcontextprotocol.io) and [Agent-to-Agent (A2A) protocol](https://google.github.io/A2A/) solve adjacent but different problems:

| Dimension | MCP | A2A |
|-----------|-----|-----|
| Primary audience | Claude Desktop, IDE plugins, single-LLM agents | Multi-vendor agent networks, orchestrators |
| Transport | stdio or HTTP/SSE (server-initiated) | HTTP/SSE (bidirectional), WebSocket |
| Discovery | Manual config or registry | `/.well-known/agent.json` agent card |
| Task model | Synchronous tool call | Asynchronous task with state transitions |
| Auth | Per-session (apiKey, bearer) | OAuth 2.1 Bearer + JWKS |
| Streaming | Tool result chunks | SSE state-transition events |

We need a clear policy for when to expose a server natively via MCP, when to bridge it via A2A, and how the bridge works.

---

## Decision

### 1. Default: MCP-native

New servers are MCP-native first. MCP is the right choice when:
- The consumer is Claude Desktop, VS Code Copilot, or a single LLM agent.
- Latency matters and synchronous tool calls are acceptable.
- No multi-vendor orchestration layer exists.

### 2. Add A2A bridge when interop is required

The `A2AAdapter` wraps any `EnhancedMCP` server to expose A2A-compatible HTTP endpoints. Add the bridge when:
- A downstream orchestrator speaks A2A (e.g., Google ADK, CrewAI, AutoGen with A2A plugin).
- Agent discovery is needed (`/.well-known/agent.json`).
- The caller requires async task state tracking (`submitted → working → completed`).
- Push notifications (webhook callbacks) are required by the caller.

### 3. Bridge boundary is the MCP tool call

The adapter maps every A2A task to exactly one MCP tool call. Complex orchestration (fan-out, chaining, consensus) stays in the A2A orchestrator layer — the bridge does not implement it.

```
A2A Orchestrator
      │  POST /tasks/sendSubscribe
      ▼
 A2AAdapter (HTTP/SSE)
      │  await mcp_server.call_tool(tool_name, arguments)
      ▼
 EnhancedMCP (tool handler)
      │
      ▼
 Result → SSE events → webhook callbacks
```

### 4. Streaming via SSE

`stream_task()` emits three events in sequence:
1. `submitted` — task accepted
2. `working` — tool invocation started
3. `completed` | `failed` — final result or error

Consumers that do not need streaming call `handle_task()` for a blocking response.

### 5. Push notifications via webhook

`handle_task(webhook_url=...)` POSTs each state transition to the caller's webhook.  
The adapter:
- Uses `httpx.AsyncClient` with a 5-second timeout.
- Logs a warning and continues on delivery failure (fire-and-forget semantics).
- Agent card advertises `pushNotifications: true` only when a webhook endpoint is registered.

---

## Consequences

**Positive:**
- One server codebase; two protocol surfaces with no duplication.
- `A2AAdapter` is zero-dependency for the MCP server — only the examples require Starlette/uvicorn.
- Agent card is derived from live tool schemas — no manual synchronization.
- Streaming and push notifications are fully operational (not just claimed).

**Negative / Trade-offs:**
- A2A task granularity matches MCP tool granularity — one tool per task. Multi-step workflows require orchestration above this layer.
- Push notification delivery is best-effort; callers that require at-least-once delivery must implement their own retry.
- `A2AAdapter` does not implement A2A authentication verification — the HTTP server layer (Starlette/FastAPI middleware) is responsible for validating Bearer tokens.

---

## Alternatives Considered

**Implement A2A natively without MCP:** Rejected — duplicates all tool logic, loses EnhancedMCP features (caching, rate-limiting, telemetry, auth).

**Use a full A2A SDK:** No stable Python A2A SDK exists as of 2026-04; the spec is evolving. A thin adapter is easier to evolve alongside the spec.

**gRPC or WebSocket streaming:** Out of scope for initial bridge; SSE is sufficient for status updates and is HTTP-native.
