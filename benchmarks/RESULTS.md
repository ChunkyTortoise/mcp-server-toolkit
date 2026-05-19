# Benchmark Results

Last run: 2026-05-19 | Python 3.12.13 | macOS (Apple Silicon)

## L1 Cache Latency (in-memory, `cached_tool`)

| Metric | Value |
|---|---|
| Cache HIT P50 | 0.008ms |
| Cache HIT P95 | 0.009ms |
| Cache MISS P50 | 0.024ms |
| Cache MISS P95 | 0.030ms |
| Speedup | **3.1x** faster on cache hit |

500 iterations, 20 warmup calls. Backend calls avoided: 499 of 1020 total calls (same output as `bench_cache.py`).

## Reproducing

```bash
python benchmarks/bench_cache.py
# or
make benchmark
```

No API keys required. Benchmark uses an in-process mock tool with `asyncio.sleep(0)` to
measure cache overhead only, not tool computation time.

## Notes

- HIT latency is dict lookup + coroutine scheduling overhead (~0.008ms P50)
- MISS latency includes cache key computation + async set (~0.024ms P50)
- Real tool latency dominates in production (LLM calls ~500-2000ms, DB queries ~10-100ms)
- The L1 cache eliminates the tool call entirely -- 3.1x speedup measured here is a floor;
  speedup against a real LLM call would be 70,000-300,000x
