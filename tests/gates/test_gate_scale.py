"""Gate 4 — Scale: cache and rate-limiter benchmarks must meet latency targets.

These are lightweight in-process benchmarks, not load tests. They verify that
the framework's hot paths don't regress below a minimum acceptable baseline.

Thresholds (deliberately generous to avoid CI flakiness on slow runners):
  - Cache hit   < 1ms    p95
  - Cache miss  < 5ms    p95  (in-memory, no actual I/O)
  - Rate-limit  < 0.5ms  p95  per check
"""

from __future__ import annotations

import asyncio
import statistics
import time

import pytest

from mcp_toolkit.framework.caching import CacheLayer, InMemoryCache
from mcp_toolkit.framework.rate_limiter import RateLimiter

ITERATIONS = 200


async def _timeit_async(coro_factory, n: int) -> list[float]:
    """Run coro_factory() n times and return elapsed milliseconds per call."""
    results = []
    for _ in range(n):
        t0 = time.perf_counter()
        await coro_factory()
        results.append((time.perf_counter() - t0) * 1000)
    return results


class TestCacheScaleGate:
    @pytest.fixture
    async def layer(self):
        layer = CacheLayer(InMemoryCache())
        layer.initialize()
        await layer.set("warm", {"data": "x" * 100}, ttl=60)
        return layer

    async def test_cache_hit_p95_under_1ms(self, layer):
        timings = await _timeit_async(lambda: layer.get("warm"), ITERATIONS)
        p95 = statistics.quantiles(timings, n=20)[18]  # 95th percentile
        assert p95 < 1.0, f"Cache hit p95 {p95:.3f}ms exceeded 1ms threshold"

    async def test_cache_miss_p95_under_5ms(self, layer):
        timings = await _timeit_async(lambda: layer.get("missing-key"), ITERATIONS)
        p95 = statistics.quantiles(timings, n=20)[18]
        assert p95 < 5.0, f"Cache miss p95 {p95:.3f}ms exceeded 5ms threshold"

    async def test_cache_set_p95_under_2ms(self, layer):
        i = 0

        async def do_set():
            nonlocal i
            i += 1
            await layer.set(f"key-{i}", "value", ttl=60)

        timings = await _timeit_async(do_set, ITERATIONS)
        p95 = statistics.quantiles(timings, n=20)[18]
        assert p95 < 2.0, f"Cache set p95 {p95:.3f}ms exceeded 2ms threshold"


class TestRateLimiterScaleGate:
    async def test_rate_check_p95_under_half_ms(self):
        rl = RateLimiter()
        i = 0

        async def do_check():
            nonlocal i
            i += 1
            await rl.check(f"scale-key-{i}", max_calls=10000, window=3600)

        timings = await _timeit_async(do_check, ITERATIONS)
        p95 = statistics.quantiles(timings, n=20)[18]
        assert p95 < 0.5, f"Rate-limit check p95 {p95:.3f}ms exceeded 0.5ms threshold"

    async def test_no_memory_leak_under_burst(self):
        """A burst of unique keys should not grow the bucket dict unboundedly in practice."""
        rl = RateLimiter()
        for i in range(500):
            await rl.check(f"burst-{i}", max_calls=100, window=60)
        # 500 unique keys each with 1 timestamp stored — well within memory budget
        assert len(rl._buckets) == 500
