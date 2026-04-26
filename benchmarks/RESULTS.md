# Benchmark Results

Last run: 2026-04-25 | Python 3.12.13 | macOS (Apple Silicon)

## L1 Cache Latency (in-memory, `cached_tool`)

| Metric | Value |
|---|---|
| Cache HIT P50 | 0.007ms |
| Cache HIT P95 | 0.008ms |
| Cache MISS P50 | 0.023ms |
| Cache MISS P95 | 0.025ms |
| Speedup | **3.1x** faster on cache hit |

500 iterations, 20 warmup calls. Backend calls avoided: 499 of 500 hit iterations (99.8%).

## Reproducing

```bash
python benchmarks/bench_cache.py
# or
make benchmark
```

No API keys required. Benchmark uses an in-process mock tool with `asyncio.sleep(0)` to
measure cache overhead only, not tool computation time.

## Notes

- HIT latency is dict lookup + coroutine scheduling overhead (~0.007ms P50)
- MISS latency includes cache key computation + async set (~0.023ms P50)
- Real tool latency dominates in production (LLM calls ~500-2000ms, DB queries ~10-100ms)
- The L1 cache eliminates the tool call entirely -- 3.1x speedup measured here is a floor;
  speedup against a real LLM call would be 70,000-300,000x
