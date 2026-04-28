# Quality Eval Results

Last run: 2026-04-26 23:25 UTC
Mode: deterministic only

## Summary

**10/10 tasks passed** | Elapsed: 556ms

## Results by Category

### Routing (3/3)

```
  [PASS] q-routing-01: query_cheap selects cheapest available provider
  [PASS] q-routing-02: query_best selects highest-quality provider first
  [PASS] q-routing-03: Circuit breaker opens after 3 failures
```

### Costing (2/2)

```
  [PASS] q-cost-01: 1M input tokens on gpt-5.5 costs $2.00
  [PASS] q-cost-02: Claude Haiku is cheaper than Claude Sonnet for same workload
```

### Auth (3/3)

```
  [PASS] q-auth-01: Valid HS256 JWT authenticates successfully
  [PASS] q-auth-02: Expired JWT is rejected (> leeway threshold)
  [PASS] q-auth-03: JWT signed with wrong secret is rejected
```

### Cache (2/2)

```
  [PASS] q-cache-01: Cache hit returns stored value
  [PASS] q-cache-02: Cache key generation is deterministic
```

## Reproducing

```bash
# Deterministic only (no API key needed):
python evals/quality/runner.py

# With LLM-as-judge scoring:
ANTHROPIC_API_KEY=sk-... python evals/quality/runner.py --judge
```

## Coverage

| Category | Cases | What it tests |
|----------|-------|----------------|
| routing  | 3     | Provider selection priority, circuit-breaker trip |
| costing  | 2     | Per-model pricing accuracy |
| auth     | 3     | JWT validation (valid, expired, wrong secret) |
| cache    | 2     | Hit/miss semantics, key determinism |
