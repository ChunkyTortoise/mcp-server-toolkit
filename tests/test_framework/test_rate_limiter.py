"""Tests for rate limiter module."""

from mcp_toolkit.framework.rate_limiter import RateLimitConfig, RateLimiter


class TestRateLimiter:
    async def test_allows_under_limit(self, rate_limiter):
        result = await rate_limiter.check("test-key", max_calls=5, window=60)
        assert result is True

    async def test_blocks_over_limit(self, rate_limiter):
        for _ in range(5):
            await rate_limiter.check("over-key", max_calls=5, window=60)
        result = await rate_limiter.check("over-key", max_calls=5, window=60)
        assert result is False

    async def test_separate_keys_independent(self, rate_limiter):
        for _ in range(5):
            await rate_limiter.check("key-a", max_calls=5, window=60)
        result_a = await rate_limiter.check("key-a", max_calls=5, window=60)
        result_b = await rate_limiter.check("key-b", max_calls=5, window=60)
        assert result_a is False
        assert result_b is True

    async def test_reset_key(self, rate_limiter):
        for _ in range(5):
            await rate_limiter.check("reset-key", max_calls=5, window=60)
        await rate_limiter.reset("reset-key")
        result = await rate_limiter.check("reset-key", max_calls=5, window=60)
        assert result is True

    async def test_reset_all(self, rate_limiter):
        for _ in range(5):
            await rate_limiter.check("all-1", max_calls=5, window=60)
            await rate_limiter.check("all-2", max_calls=5, window=60)
        await rate_limiter.reset_all()
        r1 = await rate_limiter.check("all-1", max_calls=5, window=60)
        r2 = await rate_limiter.check("all-2", max_calls=5, window=60)
        assert r1 is True
        assert r2 is True

    def test_get_remaining(self, rate_limiter):
        remaining = rate_limiter.get_remaining("fresh-key")
        assert remaining == 100  # default

    async def test_get_remaining_after_calls(self, rate_limiter):
        await rate_limiter.check("rem-key", max_calls=10, window=60)
        await rate_limiter.check("rem-key", max_calls=10, window=60)
        # configure so get_remaining uses the right config
        rate_limiter.configure("rem-key", max_calls=10, window_seconds=60)
        remaining = rate_limiter.get_remaining("rem-key")
        assert remaining == 8

    async def test_configure_custom_limit(self):
        rl = RateLimiter(default_config=RateLimitConfig(max_calls=2, window_seconds=60))
        await rl.check("d1")
        await rl.check("d1")
        result = await rl.check("d1")
        assert result is False

    async def test_uses_default_config(self, rate_limiter):
        # Default is 100 calls, 60s
        for _ in range(100):
            assert await rate_limiter.check("def-key") is True
        assert await rate_limiter.check("def-key") is False
