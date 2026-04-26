# Eval Results

Last run: 2026-04-25

## Routing Evals

```
mcp-server-toolkit routing evals -- 10/10 passed (100%)
Elapsed: 0.9ms

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

## What These Evals Do Not Cover

- Response quality (requires live API calls and LLM-as-judge)
- Tool output format correctness (covered by unit tests in tests/test_multi_llm/)
- Latency under load (see benchmarks/RESULTS.md)
- Cost calculation accuracy (covered by tests/test_multi_llm/test_pricing.py)
