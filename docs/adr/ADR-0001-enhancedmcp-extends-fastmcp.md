# ADR-0001: EnhancedMCP Extends FastMCP (Inheritance over Composition)

**Status:** Accepted
**Date:** 2026-03-01
**Deciders:** Cayman Roden

---

## Context

The MCP SDK provides `FastMCP` as the primary server base class. We need to add production
middleware (caching, rate limiting, auth, telemetry) to every server in the toolkit.

Two approaches were considered:

**Option A -- Inheritance:** `EnhancedMCP(FastMCP)` adds decorators and properties directly
to the server class. All toolkit servers inherit from `EnhancedMCP`.

**Option B -- Composition:** A separate `MiddlewareStack` wraps a plain `FastMCP` instance.
Servers hold a reference to the stack and call into it.

---

## Decision

**Inheritance (Option A).** `EnhancedMCP` extends `FastMCP` in
`mcp_toolkit/framework/base_server.py`.

---

## Rationale

- **Decorator API**: `@mcp.cached_tool(ttl=300)` reads naturally as a server-level decorator.
  With composition, callers would need `@mcp.middleware.cached_tool(...)`, which leaks the
  middleware boundary into user code.
- **FastMCP stability**: The FastMCP API is stable and well-tested. The MCP SDK team explicitly
  designs FastMCP for subclassing (it uses `__init_subclass__` hooks internally).
- **Test client**: `MCPTestClient` accepts any `FastMCP` instance. Since `EnhancedMCP` IS-A
  `FastMCP`, the test client works without modification.
- **Tradeoff accepted**: Inheritance couples `EnhancedMCP` to `FastMCP`'s internals. If the
  MCP SDK changes `FastMCP`'s constructor signature, `EnhancedMCP.__init__` must be updated.
  This is acceptable given the SDK's stable release cadence and the directness of the coupling.

---

## Consequences

- Every toolkit server (`analytics`, `crm_ghl`, etc.) gets caching, rate limiting, and
  telemetry for free by importing `EnhancedMCP`.
- Adding new middleware means updating `EnhancedMCP` and its tests -- one place, one PR.
- If a future toolkit server needs a different middleware subset, it can override or skip
  specific setup methods (`_setup_caching`, `_setup_telemetry`).
- Type checking: `EnhancedMCP` is a valid `FastMCP` everywhere the SDK accepts one. No
  casting or protocol gymnastics needed.
