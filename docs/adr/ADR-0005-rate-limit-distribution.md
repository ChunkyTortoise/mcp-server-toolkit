# ADR-0005: Rate Limiter Scope and Distribution

**Status:** Accepted
**Date:** 2026-04-26
**Revised:** 2026-05-18 (corrected to match the implementation)

## Context

`RateLimiter` (`mcp_toolkit/framework/rate_limiter.py`) is an in-process
sliding-window limiter. Callers pass an arbitrary string `key` to
`await check(key, max_calls=None, window=None)`; per-key limits are configured
via `configure(prefix, max_calls, window_seconds)` and resolved by longest
prefix match, falling back to a default `RateLimitConfig`.

Known gaps of an in-process limiter:

1. **No cross-process coordination** — horizontally scaled servers each keep
   separate counters, so a client can exceed its limit by hitting different
   instances.
2. **Key isolation is the caller's responsibility** — the limiter does not
   derive a caller identity. If callers pass a constant (or no) `key`, all
   traffic shares one bucket and the limit becomes per-process, not per-client.
3. **`check()` is not concurrency-safe** — it does an unsynchronized
   read-modify-write on the timestamp list, so concurrent awaits on the same
   key can admit calls over the limit.

## Decision

**The in-process limiter is the default and only shipped backend.** Most MCP
deployments are single-process stdio servers where cross-instance coordination
is irrelevant.

**Per-client isolation is delegated to the caller** via the `key` argument
(e.g. pass an authenticated client/user id). The library deliberately does not
infer caller identity, because identity lives in the transport/auth layer, not
the limiter.

**Concurrency safety** is resolved by guarding the `check()` critical section
with an `asyncio.Lock` (tracked in the honesty-reconciliation work, Wave 1.11).

## Future work (NOT implemented)

These were previously documented as shipped; they do not exist in the codebase
and are recorded here as deferred:

- **Redis-backed distributed window** — a cross-process backend (e.g. a Redis
  `ZADD`/`ZREMRANGEBYSCORE`/`ZCARD` sliding window) behind a `redis` extra. No
  `RedisSlidingWindow` class and no pluggable-backend constructor exist today.
- **Automatic caller-ID resolution** — resolving `caller_id` / `client_id` /
  `user_id` from the request context with a logged warning on fallback.

## Alternatives rejected

- **Token bucket** — more burst-friendly but harder to reason about for LLM API
  quota management; a sliding window maps directly to upstream per-minute quotas.
- **Sticky routing / client affinity** — delegates enforcement to the load
  balancer, which is outside this library's scope.
