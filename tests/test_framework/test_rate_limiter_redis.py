"""Tests for the Redis sliding-window backend (ADR-0005).

Unit tests drive a miniature in-process Redis double shared between client
objects, which is what makes cross-process counter behavior testable. The
integration class at the bottom talks to a real Redis and only runs with
INTEGRATION=1 and REDIS_URL set, mirroring the Postgres integration tests:

    INTEGRATION=1 REDIS_URL=redis://localhost:6379 \
        pytest tests/test_framework/test_rate_limiter_redis.py
"""

from __future__ import annotations

import fnmatch
import os
import uuid

import pytest

import mcp_toolkit.framework.rate_limiter as rate_limiter_module
from mcp_toolkit.framework.rate_limiter import RateLimiter, RedisSlidingWindow


class FakeRedisServer:
    """Miniature Redis double: shared sorted sets with the ops the window uses."""

    def __init__(self) -> None:
        self.zsets: dict[str, dict[str, float]] = {}
        self.down = False

    def zremrangebyscore(self, key: str, min_score: float | str, max_score: float) -> int:
        lo = float("-inf") if min_score == "-inf" else float(min_score)
        zset = self.zsets.get(key, {})
        pruned = [m for m, score in zset.items() if lo <= score <= max_score]
        for member in pruned:
            del zset[member]
        return len(pruned)

    def zadd(self, key: str, mapping: dict[str, float]) -> int:
        zset = self.zsets.setdefault(key, {})
        new = [m for m in mapping if m not in zset]
        zset.update(mapping)
        return len(new)

    def zcard(self, key: str) -> int:
        return len(self.zsets.get(key, {}))

    def expire(self, key: str, ttl: int) -> bool:
        return key in self.zsets  # TTL expiry is not modelled by this double

    def zrem(self, key: str, member: str) -> int:
        zset = self.zsets.get(key, {})
        if member in zset:
            del zset[member]
            return 1
        return 0

    def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self.zsets:
                del self.zsets[key]
                removed += 1
        return removed

    def keys(self, pattern: str) -> list[str]:
        return [k for k in self.zsets if fnmatch.fnmatch(k, pattern)]


class FakePipeline:
    """Queues commands and runs them in one shot, like a MULTI/EXEC pipeline."""

    def __init__(self, client: FakeRedisClient) -> None:
        self._client = client
        self._ops: list[tuple[str, tuple, dict]] = []

    async def __aenter__(self) -> FakePipeline:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    def zremrangebyscore(self, *args: object, **kwargs: object) -> None:
        self._ops.append(("zremrangebyscore", args, kwargs))

    def zadd(self, *args: object, **kwargs: object) -> None:
        self._ops.append(("zadd", args, kwargs))

    def zcard(self, *args: object, **kwargs: object) -> None:
        self._ops.append(("zcard", args, kwargs))

    def expire(self, *args: object, **kwargs: object) -> None:
        self._ops.append(("expire", args, kwargs))

    async def execute(self) -> list:
        self._client.raise_if_down()
        results = [
            getattr(self._client.server, name)(*args, **kwargs) for name, args, kwargs in self._ops
        ]
        self._ops.clear()
        return results


class FakeRedisClient:
    """Async client shape of redis.asyncio, backed by a FakeRedisServer."""

    def __init__(self, server: FakeRedisServer | None = None) -> None:
        self.server = server or FakeRedisServer()

    def raise_if_down(self) -> None:
        if self.server.down:
            raise ConnectionError("fake redis is down")

    def pipeline(self, transaction: bool = True) -> FakePipeline:
        return FakePipeline(self)

    async def zrem(self, key: str, member: str) -> int:
        self.raise_if_down()
        return self.server.zrem(key, member)

    async def delete(self, *keys: str) -> int:
        self.raise_if_down()
        return self.server.delete(*keys)

    async def keys(self, pattern: str) -> list[str]:
        self.raise_if_down()
        return self.server.keys(pattern)


class Clock:
    """Module-scoped clock double: `time` inside rate_limiter is swapped for it."""

    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def time(self) -> float:
        return self.now

    def monotonic(self) -> float:
        return self.now


def make_window(server: FakeRedisServer | None = None, **kwargs) -> tuple[RedisSlidingWindow, FakeRedisServer]:
    """A RedisSlidingWindow wired to a fake client, the way test_caching injects."""
    server = server or FakeRedisServer()
    window = RedisSlidingWindow(**kwargs)
    window._client = FakeRedisClient(server)
    return window, server


class TestRedisSlidingWindow:
    async def test_two_limiters_share_one_counter(self):
        """Two limiter instances (as in two server processes) enforce one limit."""
        server = FakeRedisServer()
        window_a, _ = make_window(server)
        window_b, _ = make_window(server)
        a = RateLimiter(backend=window_a)
        b = RateLimiter(backend=window_b)

        assert await a.check("shared", max_calls=3, window=60) is True
        assert await b.check("shared", max_calls=3, window=60) is True
        assert await a.check("shared", max_calls=3, window=60) is True
        assert await b.check("shared", max_calls=3, window=60) is False
        assert await a.check("shared", max_calls=3, window=60) is False

    async def test_separate_keys_stay_independent(self):
        server = FakeRedisServer()
        window, _ = make_window(server)
        rl = RateLimiter(backend=window)

        for _ in range(2):
            assert await rl.check("key-a", max_calls=2, window=60) is True
        assert await rl.check("key-a", max_calls=2, window=60) is False
        assert await rl.check("key-b", max_calls=2, window=60) is True

    async def test_window_slides(self, monkeypatch):
        clock = Clock()
        monkeypatch.setattr(rate_limiter_module, "time", clock)
        window, _ = make_window()
        rl = RateLimiter(backend=window)

        clock.now = 1_000.0
        assert await rl.check("k", max_calls=2, window=60) is True
        assert await rl.check("k", max_calls=2, window=60) is True
        assert await rl.check("k", max_calls=2, window=60) is False
        clock.now = 1_061.0
        assert await rl.check("k", max_calls=2, window=60) is True

    async def test_rejected_call_does_not_extend_window(self, monkeypatch):
        clock = Clock()
        monkeypatch.setattr(rate_limiter_module, "time", clock)
        window, _ = make_window()
        rl = RateLimiter(backend=window)

        clock.now = 1_000.0
        assert await rl.check("k", max_calls=1, window=60) is True
        clock.now = 1_030.0
        assert await rl.check("k", max_calls=1, window=60) is False
        # If the rejected call's marker had stayed, it would still be inside the
        # window here and block this call.
        clock.now = 1_061.0
        assert await rl.check("k", max_calls=1, window=60) is True

    async def test_remaining_counts_the_shared_window(self):
        server = FakeRedisServer()
        window_a, _ = make_window(server)
        window_b, _ = make_window(server)
        a = RateLimiter(backend=window_a)
        b = RateLimiter(backend=window_b)
        # remaining() resolves limits from configure()/defaults, not per-call overrides
        a.configure("k", max_calls=5, window_seconds=60)
        b.configure("k", max_calls=5, window_seconds=60)

        assert await a.check("k") is True
        assert await a.check("k") is True
        assert await b.get_remaining_async("k") == 3

    async def test_get_remaining_async_matches_for_default_limiter(self):
        rl = RateLimiter()
        rl.configure("k", max_calls=10, window_seconds=60)
        await rl.check("k")
        await rl.check("k")
        assert rl.get_remaining("k") == 8
        assert await rl.get_remaining_async("k") == 8

    async def test_get_remaining_sync_points_at_async_twin(self):
        window, _ = make_window()
        rl = RateLimiter(backend=window)
        with pytest.raises(RuntimeError, match="get_remaining_async"):
            rl.get_remaining("k")

    async def test_reset_and_reset_all(self):
        server = FakeRedisServer()
        window, _ = make_window(server)
        rl = RateLimiter(backend=window)

        await rl.check("a", max_calls=1, window=60)
        await rl.check("b", max_calls=1, window=60)
        await rl.reset("a")
        assert await rl.check("a", max_calls=1, window=60) is True
        assert await rl.check("b", max_calls=1, window=60) is False

        await rl.reset_all()
        assert await rl.check("b", max_calls=1, window=60) is True

    async def test_keys_are_prefixed(self):
        window, server = make_window()
        await window.record("mykey", limit=5, window_seconds=60)
        assert list(server.zsets) == ["mcp:ratelimit:mykey"]

    async def test_strict_mode_raises_on_connection_error(self):
        window, server = make_window()
        server.down = True
        rl = RateLimiter(backend=window)  # fallback_to_memory=False by default
        with pytest.raises(ConnectionError):
            await rl.check("k", max_calls=5, window=60)

    async def test_falls_back_to_per_process_window_on_redis_error(self):
        window, server = make_window(fallback_to_memory=True)
        server.down = True
        rl = RateLimiter(backend=window)

        # Per-process fallback still enforces the limit locally.
        assert await rl.check("k", max_calls=2, window=60) is True
        assert await rl.check("k", max_calls=2, window=60) is True
        assert await rl.check("k", max_calls=2, window=60) is False

    async def test_falls_back_when_redis_unreachable(self):
        window = RedisSlidingWindow("redis://nonexistent:9999", fallback_to_memory=True)
        rl = RateLimiter(backend=window)
        assert await rl.check("k", max_calls=1, window=60) is True
        assert await rl.check("k", max_calls=1, window=60) is False


INTEGRATION = os.environ.get("INTEGRATION") == "1"
REDIS_URL = os.environ.get("REDIS_URL", "")

pytestmark_integration = pytest.mark.skipif(
    not INTEGRATION or not REDIS_URL,
    reason="Set INTEGRATION=1 and REDIS_URL (e.g. redis://localhost:6379)",
)


class TestRedisSlidingWindowIntegration:
    """Real-Redis checks (INTEGRATION=1 + REDIS_URL), like the Postgres tests."""

    pytestmark = pytestmark_integration

    async def test_shared_limit_across_clients(self):
        key = f"itest-{uuid.uuid4().hex}"
        a = RateLimiter(backend=RedisSlidingWindow(REDIS_URL))
        b = RateLimiter(backend=RedisSlidingWindow(REDIS_URL))
        try:
            assert await a.check(key, max_calls=2, window=60) is True
            assert await b.check(key, max_calls=2, window=60) is True
            assert await a.check(key, max_calls=2, window=60) is False
            assert await b.get_remaining_async(key) == 0
        finally:
            await a.reset(key)

    async def test_reset_clears_shared_state(self):
        key = f"itest-{uuid.uuid4().hex}"
        a = RateLimiter(backend=RedisSlidingWindow(REDIS_URL))
        b = RateLimiter(backend=RedisSlidingWindow(REDIS_URL))
        try:
            await a.check(key, max_calls=1, window=60)
            assert await b.check(key, max_calls=1, window=60) is False
            await b.reset(key)
            assert await a.check(key, max_calls=1, window=60) is True
        finally:
            await a.reset(key)
