"""Per-tool rate limiting with configurable limits."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from mcp_toolkit.framework.caching import _REDIS_TRANSIENT

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Configuration for a rate limit rule."""

    max_calls: int = 100
    window_seconds: int = 60


@dataclass
class _BucketEntry:
    """Tracks calls within a time window."""

    timestamps: list[float] = field(default_factory=list)


class InMemorySlidingWindow:
    """Per-process sliding-window counter on the monotonic clock.

    The default store for :class:`RateLimiter`, and the ``fallback_to_memory``
    fallback inside :class:`RedisSlidingWindow`. Counters are never shared with
    other processes.
    """

    def __init__(self) -> None:
        self._buckets: dict[str, _BucketEntry] = {}

    def record(self, key: str, limit: int, window_seconds: int) -> bool:
        """Record one call and return whether it is within the limit."""
        now = time.monotonic()
        cutoff = now - window_seconds

        if key not in self._buckets:
            self._buckets[key] = _BucketEntry()

        bucket = self._buckets[key]
        bucket.timestamps = [ts for ts in bucket.timestamps if ts > cutoff]

        if len(bucket.timestamps) >= limit:
            return False

        bucket.timestamps.append(now)
        return True

    @property
    def size(self) -> int:
        return len(self._buckets)

    def remaining(self, key: str, limit: int, window_seconds: int) -> int:
        """Calls still allowed for ``key`` in the current window."""
        if key not in self._buckets:
            return limit

        now = time.monotonic()
        cutoff = now - window_seconds
        bucket = self._buckets[key]
        active = [ts for ts in bucket.timestamps if ts > cutoff]
        return max(0, limit - len(active))

    def reset(self, key: str) -> None:
        self._buckets.pop(key, None)

    def reset_all(self) -> None:
        self._buckets.clear()


class RedisSlidingWindow:
    """Redis-backed sliding-window store shared across processes (ADR-0005).

    Every call adds a ZSET member scored by wall-clock time under
    ``mcp:ratelimit:<key>``. One atomic pipeline prunes members that fell out of
    the window (``ZREMRANGEBYSCORE``), records the call (``ZADD``) and counts
    what is left (``ZCARD``). A call that lands over the limit has its member
    removed again, so rejected calls do not stretch the window. The pipeline
    also sets ``EXPIRE`` to one window, refreshed on each record, so idle
    buckets clean themselves up.

    Members are scored with ``time.time()``, not ``time.monotonic()``: the
    counter is shared across processes and hosts, whose monotonic clocks are not
    comparable. Clock skew between instances shifts window edges by the skew
    amount.

    By default connectivity errors are **raised** so callers know Redis is down
    and limits are not being enforced where they expect. Pass
    ``fallback_to_memory=True`` to fall back to a per-process in-memory window
    instead — that silently returns to per-process limits, which is fine for
    local development and misleading in a multi-instance deployment.

    Requires the ``redis`` extra. Usage::

        limiter = RateLimiter(backend=RedisSlidingWindow("redis://localhost:6379"))

    Args:
        redis_url:          Redis connection string (default: redis://localhost:6379).
        fallback_to_memory: When True, swallow transient errors and fall back to a
                            per-process in-memory window instead of raising.
                            Defaults to False.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        fallback_to_memory: bool = False,
    ) -> None:
        self._redis_url = redis_url
        self._fallback_to_memory = fallback_to_memory
        self._client: Any | None = None
        self._fallback = InMemorySlidingWindow()

    @staticmethod
    def _redis_key(key: str) -> str:
        return f"mcp:ratelimit:{key}"

    async def _get_client(self) -> Any | None:
        if self._client is not None:
            return self._client
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(self._redis_url, decode_responses=True)
            await client.ping()  # type: ignore[misc]  # redis.asyncio stub types ping() as sync
            self._client = client
            return self._client
        except _REDIS_TRANSIENT as exc:
            if self._fallback_to_memory:
                logger.warning("Redis unavailable (%s); falling back to per-process limits.", exc)
                return None
            raise
        except Exception as exc:
            if self._fallback_to_memory:
                logger.warning("Redis connection error (%s); falling back to per-process limits.", exc)
                return None
            raise

    async def record(self, key: str, limit: int, window_seconds: int) -> bool:
        """Record one call and return whether it is within the limit."""
        client = await self._get_client()
        if client is None:
            return self._fallback.record(key, limit, window_seconds)
        try:
            now = time.time()
            member = f"{now:.6f}:{uuid.uuid4().hex}"
            redis_key = self._redis_key(key)
            async with client.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(redis_key, "-inf", now - window_seconds)
                pipe.zadd(redis_key, {member: now})
                pipe.zcard(redis_key)
                pipe.expire(redis_key, window_seconds)
                # Results follow the queued order: [pruned, added, card, expired].
                count = (await pipe.execute())[2]
            if count > limit:
                # The call is over the limit: remove its marker so a rejected
                # call does not extend the window, matching the in-memory store,
                # which never records refusals.
                await client.zrem(redis_key, member)
                return False
            return True
        except _REDIS_TRANSIENT as exc:
            if self._fallback_to_memory:
                logger.warning("Redis record error (%s); using per-process fallback window.", exc)
                return self._fallback.record(key, limit, window_seconds)
            raise

    async def remaining(self, key: str, limit: int, window_seconds: int) -> int:
        """Calls still allowed for ``key`` in the current window."""
        client = await self._get_client()
        if client is None:
            return self._fallback.remaining(key, limit, window_seconds)
        try:
            now = time.time()
            redis_key = self._redis_key(key)
            async with client.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(redis_key, "-inf", now - window_seconds)
                pipe.zcard(redis_key)
                # Results follow the queued order: [pruned, card].
                count = (await pipe.execute())[1]
            return max(0, limit - count)
        except _REDIS_TRANSIENT as exc:
            if self._fallback_to_memory:
                logger.warning("Redis count error (%s); using per-process fallback window.", exc)
                return self._fallback.remaining(key, limit, window_seconds)
            raise

    async def reset(self, key: str) -> None:
        client = await self._get_client()
        if client is None:
            self._fallback.reset(key)
            return
        try:
            await client.delete(self._redis_key(key))
        except _REDIS_TRANSIENT as exc:
            if self._fallback_to_memory:
                logger.warning("Redis reset error (%s); using per-process fallback window.", exc)
                self._fallback.reset(key)
                return
            raise

    async def reset_all(self) -> None:
        client = await self._get_client()
        if client is None:
            self._fallback.reset_all()
            return
        try:
            keys = await client.keys("mcp:ratelimit:*")
            if keys:
                await client.delete(*keys)
        except _REDIS_TRANSIENT as exc:
            if self._fallback_to_memory:
                logger.warning("Redis reset error (%s); using per-process fallback window.", exc)
                self._fallback.reset_all()
                return
            raise


class RateLimiter:
    """Sliding-window rate limiter.

    Counters live per process (:class:`InMemorySlidingWindow`) by default. Pass
    ``backend=RedisSlidingWindow(redis_url)`` to share the sliding window across
    processes and hosts (ADR-0005, requires the ``redis`` extra).
    """

    def __init__(
        self,
        default_config: RateLimitConfig | None = None,
        backend: RedisSlidingWindow | None = None,
    ) -> None:
        self._default = default_config or RateLimitConfig()
        self._backend = backend
        self._memory = InMemorySlidingWindow()
        self._configs: dict[str, RateLimitConfig] = {}

    def configure(self, key: str, max_calls: int, window_seconds: int) -> None:
        """Set a custom rate limit for a specific key prefix."""
        self._configs[key] = RateLimitConfig(max_calls=max_calls, window_seconds=window_seconds)

    def _get_config(self, key: str) -> RateLimitConfig:
        for prefix, config in self._configs.items():
            if key.startswith(prefix):
                return config
        return self._default

    def _resolve(self, key: str, max_calls: int | None, window: int | None) -> tuple[int, int]:
        config = self._get_config(key)
        limit = max_calls if max_calls is not None else config.max_calls
        window_secs = window if window is not None else config.window_seconds
        return limit, window_secs

    async def check(
        self,
        key: str,
        max_calls: int | None = None,
        window: int | None = None,
    ) -> bool:
        """Check if a call is allowed under the rate limit.

        Returns True if allowed, False if rate limit exceeded.
        """
        limit, window_secs = self._resolve(key, max_calls, window)
        if self._backend is not None:
            return await self._backend.record(key, limit, window_secs)
        return self._memory.record(key, limit, window_secs)

    async def reset(self, key: str) -> None:
        """Reset the rate limit counter for a key."""
        if self._backend is not None:
            await self._backend.reset(key)
            return
        self._memory.reset(key)

    async def reset_all(self) -> None:
        """Reset all rate limit counters."""
        if self._backend is not None:
            await self._backend.reset_all()
            return
        self._memory.reset_all()

    def get_remaining(self, key: str) -> int:
        """Get the number of remaining calls allowed in the current window.

        Synchronous by design for the per-process default. With a
        :class:`RedisSlidingWindow` backend the count lives in Redis and cannot
        be read synchronously; use ``await get_remaining_async(key)``.
        """
        if self._backend is not None:
            raise RuntimeError(
                "get_remaining() cannot reach the RedisSlidingWindow backend synchronously; "
                "use `await get_remaining_async(key)` instead."
            )
        limit, window_secs = self._resolve(key, None, None)
        return self._memory.remaining(key, limit, window_secs)

    async def get_remaining_async(self, key: str) -> int:
        """Same as :meth:`get_remaining`, but also works with a Redis backend."""
        limit, window_secs = self._resolve(key, None, None)
        if self._backend is not None:
            return await self._backend.remaining(key, limit, window_secs)
        return self._memory.remaining(key, limit, window_secs)
