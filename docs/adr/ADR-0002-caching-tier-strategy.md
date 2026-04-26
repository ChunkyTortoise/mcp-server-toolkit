# ADR-0002: Two-Tier Caching Strategy (L1 In-Memory + L2 Redis)

**Status:** Accepted
**Date:** 2026-03-01
**Deciders:** Cayman Roden

---

## Context

MCP tool responses can be expensive to produce (LLM API calls, database queries, web scrapes).
We need a caching strategy that works out-of-the-box for single-instance deployments and scales
to multi-instance deployments without a code change in tool implementations.

Three options were considered:

**Option A -- L1 only (in-memory):** Simple TTL dict. Fast, zero dependencies. Lost on restart
or across instances.

**Option B -- L2 only (Redis):** Always durable, shareable across instances. Requires Redis
infrastructure even for local development.

**Option C -- L1 + L2 (tiered):** L1 always on, L2 optional. L1 hit avoids network round-trip.
L2 hit avoids recomputation. L2 miss falls through to the tool.

---

## Decision

**Tiered L1 + L2 (Option C).** `CacheLayer` in `mcp_toolkit/framework/caching.py` wraps an
`InMemoryCache` (L1) by default. Pass `RedisCache(url=...)` as the backend to enable L2.

---

## Rationale

- **Zero-config default**: `EnhancedMCP` initializes `CacheLayer(InMemoryCache())` automatically.
  Developers get caching in local development and testing without standing up Redis.
- **Production upgrade path**: Switching to Redis is one line: `CacheLayer(backend=RedisCache(...))`.
  Tool implementations do not change.
- **L1 miss cost**: L1 is a dict lookup (sub-microsecond). An L1 miss that hits L2 adds ~1ms
  network round-trip. An L2 miss falls through to the tool. This is acceptable for all current
  tool categories (LLM calls: ~1s, DB queries: ~10-100ms, web scrapes: ~500ms-5s).
- **Tradeoff accepted**: L1 caches are per-process -- two server instances serving the same
  tool will have separate L1 caches, causing redundant cache misses. L2 (Redis) eliminates
  this at the cost of infrastructure dependency. The deployment guide documents this tradeoff.

---

## TTL Policy

Default TTL is 300 seconds (5 minutes), configurable per tool via `@mcp.cached_tool(ttl=N)`.
There is no explicit cache invalidation beyond TTL expiry. Tools that must invalidate on
write (e.g., CRM updates) should use `ttl=0` (bypass) or implement domain-specific
invalidation by calling `cache.delete(key)` after a write operation.

---

## Consequences

- Local development and CI run with zero external dependencies.
- Production deployments with multiple instances should configure Redis L2.
- Cache keys are derived from tool name + argument hash. Same arguments always hit the same
  key -- deterministic, but means cached results do not reflect external state changes until TTL
  expires. Tools with real-time requirements (e.g., `list_providers` circuit breaker state)
  bypass the cache explicitly (`ttl=0`).
