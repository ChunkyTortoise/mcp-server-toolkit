# ADR-0005: Rate Limiter Distribution Strategy

**Status:** Accepted  
**Date:** 2026-04-26

## Context

`RateLimiter` uses an in-process sliding-window list. This works for single-instance MCP servers but has two known gaps:

1. **Global fallback**: when a tool call provides no `caller_id`/`client_id`/`user_id`, all callers share one `"default"` bucket, making rate limits effectively per-server-process rather than per-client.
2. **No cross-process coordination**: horizontally scaled servers each maintain separate counters, so a client can exceed its limit by hitting different instances.

## Decision

**In-process limiter stays the default.** Most MCP server deployments are single-process stdio servers where cross-instance coordination is irrelevant.

**Caller-ID resolution order:** explicit kwarg (`caller_id` > `client_id` > `user_id`) → fall back to `"default"` with a `logging.WARNING` so operators know limits aren't per-client.

**Redis distributed backend ships as opt-in (W1.4+):** a `RedisSlidingWindow` using `ZADD`/`ZREMRANGEBYSCORE`/`ZCARD` atomic pipeline, gated behind `redis` extra. Callers construct `RateLimiter(backend=RedisSlidingWindow(redis_url))`.

## Consequences

- Operators running multi-instance servers must opt in to Redis backend and supply `REDIS_URL`.
- Warning log on `"default"` caller fallback surfaces misconfigured deployments early.
- No silent correctness bug, the in-process fallback is documented, not hidden.

## Alternatives Rejected

- **Token bucket**: more burst-friendly but harder to reason about for LLM API quota management; sliding window maps directly to upstream rate limit windows.
- **Sticky routing / client affinity**: delegates enforcement to the load balancer, which is outside this library's scope.

## Decision notes (2026-10-25)

The implemented `RedisSlidingWindow` follows the design above, with four details the original decision did not pin down:

- **Clock.** Members are scored with `time.time()`, not `time.monotonic()`: the counter is shared across processes and hosts, whose monotonic clocks are not comparable. Clock skew between instances therefore shifts window edges by the skew amount. The in-process store keeps the monotonic clock.
- **Refusals do not extend the window.** The atomic pipeline runs `ZREMRANGEBYSCORE`/`ZADD`/`ZCARD` (prune, record, count); when the count lands over the limit the call's marker is removed again. The in-memory store never records refusals, and a rejected call must not stretch the window either.
- **Key hygiene.** The pipeline also sets `EXPIRE` to one window, refreshed on each record, so idle buckets clean themselves up instead of accumulating in Redis.
- **`get_remaining()` stays synchronous** for the in-process default; reading the count from Redis needs I/O, so `get_remaining_async()` was added and the sync method raises a `RuntimeError` pointing at it when a Redis backend is configured.

Failure semantics follow `RedisCache`: transient errors raise unless `fallback_to_memory=True`, which returns to per-process limits — acceptable for local development, misleading for a multi-instance deployment.
