#!/usr/bin/env python3
"""Cache performance benchmark for mcp-server-toolkit.

Measures L1 in-memory cache hit vs miss latency for a cached MCP tool.
No external dependencies, no API keys required.

Usage:
    python benchmarks/bench_cache.py
    make benchmark
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_toolkit.framework.base_server import EnhancedMCP

ITERATIONS = 500
WARMUP = 20


async def run() -> dict[str, float]:
    mcp = EnhancedMCP("bench-server")

    call_count = 0

    @mcp.cached_tool(ttl=60)
    async def echo(value: str) -> str:
        nonlocal call_count
        call_count += 1
        # Simulate minimal work so we measure cache overhead, not computation
        await asyncio.sleep(0)
        return f"echoed: {value}"

    client_args = {"value": "hello"}

    # Warmup: prime the cache
    for _ in range(WARMUP):
        await mcp.call_tool("echo", client_args)
    warmup_backend = call_count

    # Measure cache hits (same args, cache is warm)
    hit_times: list[float] = []
    for _ in range(ITERATIONS):
        t0 = time.perf_counter()
        await mcp.call_tool("echo", client_args)
        hit_times.append((time.perf_counter() - t0) * 1_000)
    hit_loop_backend = call_count - warmup_backend

    # Measure cache misses (unique args each time -- always a miss)
    miss_times: list[float] = []
    for i in range(ITERATIONS):
        t0 = time.perf_counter()
        await mcp.call_tool("echo", {"value": f"unique-{i}"})
        miss_times.append((time.perf_counter() - t0) * 1_000)

    cacheable_calls = WARMUP + ITERATIONS
    cacheable_backend = warmup_backend + hit_loop_backend
    return {
        "hit_p50_ms": statistics.median(hit_times),
        "hit_p95_ms": sorted(hit_times)[int(ITERATIONS * 0.95)],
        "miss_p50_ms": statistics.median(miss_times),
        "miss_p95_ms": sorted(miss_times)[int(ITERATIONS * 0.95)],
        "speedup_x": statistics.median(miss_times) / statistics.median(hit_times),
        "backend_calls_total": call_count,
        "hit_loop_backend": hit_loop_backend,
        "cacheable_calls": cacheable_calls,
        "cacheable_served_from_cache": cacheable_calls - cacheable_backend,
    }


def main() -> None:
    results = asyncio.run(run())

    print("\nmcp-server-toolkit cache benchmark (L1 in-memory)")
    print(f"Iterations: {ITERATIONS} | Warmup: {WARMUP}\n")
    print(f"  Cache HIT  -- P50: {results['hit_p50_ms']:.3f}ms  P95: {results['hit_p95_ms']:.3f}ms")
    print(f"  Cache MISS -- P50: {results['miss_p50_ms']:.3f}ms  P95: {results['miss_p95_ms']:.3f}ms")
    print(f"  Speedup:      {results['speedup_x']:.1f}x faster on cache hit")
    served = results["cacheable_served_from_cache"]
    cacheable = results["cacheable_calls"]
    hit_pct = 100.0 * served / cacheable
    print(
        f"  Cache effectiveness: {served} of {cacheable} cacheable calls served "
        f"from cache ({hit_pct:.1f}%); hit loop made {results['hit_loop_backend']} "
        f"of {ITERATIONS} backend calls\n"
    )


if __name__ == "__main__":
    main()
