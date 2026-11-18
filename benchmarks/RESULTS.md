# Benchmark Results

Last run: 2026-11-17 | Python 3.13.11 | macOS 27.0 (Apple M4, arm64) | raw output: [`run-2026-11-17.txt`](run-2026-11-17.txt)

## L1 Cache Latency (in-memory, `cached_tool`)

| Metric | Value |
|---|---|
| Cache HIT P50 | 0.013ms |
| Cache HIT P95 | 0.015ms |
| Cache MISS P50 | 0.028ms |
| Cache MISS P95 | 0.033ms |
| Speedup | **2.1x** faster on cache hit |

500 iterations, 20 warmup calls. Backend calls avoided: 499 of 500 hit iterations (99.8%).

Three earlier runs on the same machine the same evening printed 2.2x each. A run on 2026-04-25 (Python 3.12.13, macOS on Apple Silicon) printed 3.1x; the run above supersedes it.

## Reproducing

```bash
python benchmarks/bench_cache.py
# or
make benchmark
```

No API keys required. Benchmark uses an in-process mock tool with `asyncio.sleep(0)` to
measure cache overhead only, not tool computation time.

## Notes

- HIT latency is dict lookup + coroutine scheduling overhead (see table)
- MISS latency includes cache key computation + async set (see table)
- The speedup is the ratio of the two P50 values from one run. `benchmarks/bench_cache.py` times an in-memory `cached_tool` for 500 iterations after 20 warmup calls. The tool is an in-process mock that awaits `asyncio.sleep(0)`. There is no network and no live provider call. The run measures cache overhead, not tool work.
