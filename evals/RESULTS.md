# Eval Results

Last run: 2026-04-26

## Routing Evals

```
mcp-server-toolkit routing evals -- 26/26 passed (100%)
Elapsed: 1131.6ms

  [PASS] cheap-01: query_cheap with all providers configured selects cheapest (Gemini Flash-Lite)
  [PASS] cheap-02: query_cheap with only OpenAI configured selects gpt-4.1-nano (first OpenAI in CHEAP_PRIORITY)
  [PASS] cheap-03: query_cheap with only xAI configured selects grok fast model
  [PASS] cheap-04: query_cheap with Gemini circuit open skips all Gemini models (per-provider breaker) and falls through to OpenAI
  [PASS] cheap-05: query_cheap with Gemini and OpenAI circuits open falls through to xAI
  [PASS] best-01: query_best with all providers configured selects GPT-5.5 (first in BEST_PRIORITY)
  [PASS] best-02: query_best with only Gemini configured selects gemini-2.5-pro
  [PASS] best-03: query_best with OpenAI circuit open falls through to Gemini 2.5 Pro
  [PASS] best-04: query_best with only xAI configured selects grok reasoning model
  [PASS] cb-01: Circuit breaker opens after 3 consecutive failures
  [PASS] cache-01: set then immediate get returns stored value
  [PASS] cache-02: get on missing key returns None
  [PASS] cache-03: set with ttl=1, after 1.1s get returns None (TTL expiry)
  [PASS] cache-04: make_key is deterministic -- same args produce identical key
  [PASS] cache-05: make_key is unique -- different args produce different keys
  [PASS] cache-06: clear() empties the cache -- subsequent get returns None
  [PASS] cache-07: set overwrites an existing key with new value
  [PASS] a2a-01: handle_task with valid tool returns status completed
  [PASS] a2a-02: handle_task with unknown tool name returns status failed
  [PASS] a2a-03: get_agent_card returns dict with skills list of length >= 1
  [PASS] a2a-04: get_task_status after handle_task returns the same task status
  [PASS] a2a-05: list_tasks after two handle_task calls returns 2 entries
  [PASS] rl-01: first call to check() always returns True
  [PASS] rl-02: call at max_calls limit returns False
  [PASS] rl-03: reset() clears bucket so next call returns True
  [PASS] rl-04: get_remaining() decrements with each allowed call

All evals passed.
```

## Reproducing

```bash
python evals/run_evals.py
python evals/run_evals.py --verbose   # show all cases, not just failures
```

No API keys required. The evals test routing priority logic and circuit breaker behavior
using stub providers -- no live LLM calls.

## What These Evals Cover

| Category | Cases | Description |
|---|---|---|
| query_cheap routing | cheap-01 to cheap-05 | Priority-ordered provider selection under various availability scenarios |
| query_best routing | best-01 to best-04 | Best-quality routing with circuit breaker fallthrough |
| Circuit breaker | cb-01 | Verifies the 3-failure trip threshold |
| CacheLayer | cache-01 to cache-07 | In-memory set/get, TTL expiry, key generation, clear, and overwrite |
| A2AAdapter | a2a-01 to a2a-05 | Task dispatch, unknown tool failure, agent card shape, task status retrieval, list_tasks |
| RateLimiter | rl-01 to rl-04 | First-call allow, limit enforcement, reset, and get_remaining decrement |

## What These Evals Do Not Cover

- Response quality (requires live API calls and LLM-as-judge)
- Tool output format correctness (covered by unit tests in tests/test_multi_llm/)
- Latency under load (see benchmarks/RESULTS.md)
- Cost calculation accuracy (covered by tests/test_multi_llm/test_pricing.py)
