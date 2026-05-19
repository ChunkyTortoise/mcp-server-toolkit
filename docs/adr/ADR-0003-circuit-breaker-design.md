# ADR-0003: Per-Provider Circuit Breaker in multi_llm

**Status:** Accepted
**Date:** 2026-03-15
**Deciders:** Cayman Roden

---

## Context

The `multi_llm` server routes prompts to multiple LLM providers (Gemini, OpenAI, xAI/Grok).
Providers can be temporarily unavailable (rate limits, outages, quota exhaustion). Without
protection, a failing provider causes cascading errors in `query_cheap` and `query_best` which
iterate the provider list.

Two circuit breaker scopes were considered:

**Option A -- Global circuit breaker:** A single breaker trips if any provider fails. Simple
but blunt -- a Gemini outage would block OpenAI calls.

**Option B -- Per-provider circuit breakers:** Each provider has its own breaker. A Gemini
failure opens only the Gemini breaker; OpenAI and xAI remain available.

---

## Decision

**Per-provider circuit breakers (Option B).** Implemented as a `CircuitBreaker`
class in `mcp_toolkit/servers/multi_llm/models.py`. Each `GeminiProvider` and
`OpenAICompatibleProvider` instance owns its own `CircuitBreaker`, which tracks a
`_failures` counter and an `_open_until` monotonic-clock deadline (half-open on
expiry, auto-reset on first success).

---

## Thresholds

| Parameter | Value | Rationale |
|---|---|---|
| Failure threshold | 3 consecutive failures | Low enough to trip quickly on real outages; high enough to not trip on transient errors. |
| Reset after | 60 seconds | Matches typical LLM provider rate-limit windows (per-minute quotas). |
| Half-open probe | 1 request | After 60s, the next request is a probe. Success resets the breaker; failure restarts the 60s timer. |

---

## Rationale

- **Isolation**: Provider outages do not propagate. `query_cheap` tries Gemini Flash first; if
  the Gemini breaker is open, it moves to the next cheapest available provider without error.
- **Observability**: `list_providers` returns each provider's circuit state (`open`/`closed`)
  and consecutive failure count. Agents can check this before routing decisions.
- **Tradeoff accepted**: Per-provider state is in-process memory. If the server restarts, all
  breakers reset to closed. This is acceptable -- a fresh process should probe providers rather
  than inherit stale failure state from a previous process.
- **Alternative rejected**: A shared Redis-backed breaker state would survive restarts but adds
  infrastructure dependency. Given that LLM provider outages typically resolve within minutes
  (faster than a typical server restart), in-process state is sufficient.

---

## Consequences

- `query_cheap` and `query_best` silently skip providers with open breakers. Agents calling
  these tools should use `list_providers` if they need to know which providers are currently
  unavailable.
- A multi-instance deployment has independent breaker state per process. Under a provider
  outage, each process will trip its own breaker independently after 3 failures, which adds
  at most 3 * N failed requests where N is the instance count. For typical deployments (1-3
  instances), this is acceptable.
- Breaker thresholds are hardcoded. If the 3-failure threshold causes too many false positives
  in high-throughput deployments, it should be made configurable via `configure()`.
