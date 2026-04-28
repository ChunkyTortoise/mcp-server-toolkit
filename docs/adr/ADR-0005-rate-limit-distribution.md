# ADR-0005: Rate Limiter Distribution Strategy

**Status:** Accepted  
**Date:** 2026-04-26

## Context

`RateLimiter` uses an in-process sliding-window list. This works for single-instance MCP servers but has two known gaps:

1. **Global fallback** — when a tool call provides no `caller_id`/`client_id`/`user_id`, all callers share one `"default"` bucket, making rate limits effectively per-server-process rather than per-client.
2. **No cross-process coordination** — horizontally scaled servers each maintain separate counters, so a client can exceed its limit by hitting different instances.

## Decision

**In-process limiter stays the default.** Most MCP server deployments are single-process stdio servers where cross-instance coordination is irrelevant.

**Caller-ID resolution order:** explicit kwarg (`caller_id` > `client_id` > `user_id`) → fall back to `"default"` with a `logging.WARNING` so operators know limits aren't per-client.

**Redis distributed backend ships as opt-in (W1.4+):** a `RedisSlidingWindow` using `ZADD`/`ZREMRANGEBYSCORE`/`ZCARD` atomic pipeline, gated behind `redis` extra. Callers construct `RateLimiter(backend=RedisSlidingWindow(redis_url))`.

## Consequences

- Operators running multi-instance servers must opt in to Redis backend and supply `REDIS_URL`.
- Warning log on `"default"` caller fallback surfaces misconfigured deployments early.
- No silent correctness bug — the in-process fallback is documented, not hidden.

## Alternatives Rejected

- **Token bucket** — more burst-friendly but harder to reason about for LLM API quota management; sliding window maps directly to upstream rate limit windows.
- **Sticky routing / client affinity** — delegates enforcement to the load balancer, which is outside this library's scope.
