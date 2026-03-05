"""Per-tool rate limiting with configurable limits."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class RateLimitConfig:
    """Configuration for a rate limit rule."""

    max_calls: int = 100
    window_seconds: int = 60


@dataclass
class _BucketEntry:
    """Tracks calls within a time window."""

    timestamps: list[float] = field(default_factory=list)


class RateLimiter:
    """In-memory token-bucket-style rate limiter.

    Tracks call timestamps per key and rejects calls exceeding the configured limit
    within the sliding window.
    """

    def __init__(self, default_config: RateLimitConfig | None = None) -> None:
        self._default = default_config or RateLimitConfig()
        self._buckets: dict[str, _BucketEntry] = {}
        self._configs: dict[str, RateLimitConfig] = {}

    def configure(self, key: str, max_calls: int, window_seconds: int) -> None:
        """Set a custom rate limit for a specific key prefix."""
        self._configs[key] = RateLimitConfig(max_calls=max_calls, window_seconds=window_seconds)

    def _get_config(self, key: str) -> RateLimitConfig:
        for prefix, config in self._configs.items():
            if key.startswith(prefix):
                return config
        return self._default

    async def check(
        self,
        key: str,
        max_calls: int | None = None,
        window: int | None = None,
    ) -> bool:
        """Check if a call is allowed under the rate limit.

        Returns True if allowed, False if rate limit exceeded.
        """
        config = self._get_config(key)
        limit = max_calls if max_calls is not None else config.max_calls
        window_secs = window if window is not None else config.window_seconds

        now = time.monotonic()
        cutoff = now - window_secs

        if key not in self._buckets:
            self._buckets[key] = _BucketEntry()

        bucket = self._buckets[key]
        bucket.timestamps = [ts for ts in bucket.timestamps if ts > cutoff]

        if len(bucket.timestamps) >= limit:
            return False

        bucket.timestamps.append(now)
        return True

    async def reset(self, key: str) -> None:
        """Reset the rate limit counter for a key."""
        self._buckets.pop(key, None)

    async def reset_all(self) -> None:
        """Reset all rate limit counters."""
        self._buckets.clear()

    def get_remaining(self, key: str) -> int:
        """Get the number of remaining calls allowed in the current window."""
        config = self._get_config(key)
        now = time.monotonic()
        cutoff = now - config.window_seconds

        if key not in self._buckets:
            return config.max_calls

        bucket = self._buckets[key]
        active = [ts for ts in bucket.timestamps if ts > cutoff]
        return max(0, config.max_calls - len(active))
