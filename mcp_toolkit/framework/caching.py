"""Response caching layer with in-memory and Redis backends."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class CacheBackend(ABC):
    """Abstract cache backend."""

    @abstractmethod
    async def get(self, key: str) -> Any | None: ...

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int = 300) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def clear(self) -> None: ...


class InMemoryCache(CacheBackend):
    """Simple in-memory cache with TTL support."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float]] = {}

    async def get(self, key: str) -> Any | None:
        if key not in self._store:
            return None
        value, expires_at = self._store[key]
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        self._store[key] = (value, time.monotonic() + ttl)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def clear(self) -> None:
        self._store.clear()

    @property
    def size(self) -> int:
        return len(self._store)


# Exceptions that indicate a transient Redis connectivity issue.
_REDIS_TRANSIENT = (ConnectionError, TimeoutError, OSError)


class RedisCache(CacheBackend):
    """Redis-backed cache.

    By default, connectivity errors are **raised** so callers know Redis is down.
    Pass ``fallback_to_memory=True`` to silently use an in-process fallback instead —
    useful for local development where Redis may not be running.

    Args:
        redis_url:          Redis connection string (default: redis://localhost:6379).
        fallback_to_memory: When True, swallow transient errors and fall back to an
                            in-memory cache instead of raising.  Defaults to False.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        fallback_to_memory: bool = False,
    ) -> None:
        self._redis_url = redis_url
        self._fallback_to_memory = fallback_to_memory
        self._client: Any | None = None
        self._fallback = InMemoryCache()

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
                logger.warning("Redis unavailable (%s); falling back to in-memory cache.", exc)
                return None
            raise
        except Exception as exc:
            if self._fallback_to_memory:
                logger.warning("Redis connection error (%s); falling back to in-memory cache.", exc)
                return None
            raise

    async def get(self, key: str) -> Any | None:
        client = await self._get_client()
        if client is None:
            return await self._fallback.get(key)
        try:
            raw = await client.get(f"mcp:{key}")
            return json.loads(raw) if raw else None
        except _REDIS_TRANSIENT as exc:
            if self._fallback_to_memory:
                logger.warning("Redis get error (%s); using in-memory fallback.", exc)
                return await self._fallback.get(key)
            raise

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        client = await self._get_client()
        if client is None:
            await self._fallback.set(key, value, ttl)
            return
        try:
            await client.setex(f"mcp:{key}", ttl, json.dumps(value, default=str))
        except _REDIS_TRANSIENT as exc:
            if self._fallback_to_memory:
                logger.warning("Redis set error (%s); writing to in-memory fallback.", exc)
                await self._fallback.set(key, value, ttl)
                return
            raise

    async def delete(self, key: str) -> None:
        client = await self._get_client()
        if client is None:
            await self._fallback.delete(key)
            return
        try:
            await client.delete(f"mcp:{key}")
        except _REDIS_TRANSIENT as exc:
            if self._fallback_to_memory:
                logger.warning("Redis delete error (%s); using in-memory fallback.", exc)
                await self._fallback.delete(key)
                return
            raise

    async def clear(self) -> None:
        client = await self._get_client()
        if client is None:
            await self._fallback.clear()
            return
        try:
            keys = await client.keys("mcp:*")
            if keys:
                await client.delete(*keys)
        except _REDIS_TRANSIENT as exc:
            if self._fallback_to_memory:
                logger.warning("Redis clear error (%s); clearing in-memory fallback.", exc)
                await self._fallback.clear()
                return
            raise


class CacheLayer:
    """High-level caching layer that manages backends and key generation."""

    def __init__(self, backend: CacheBackend | None = None) -> None:
        self._backend = backend or InMemoryCache()
        self._initialized = False

    def initialize(self, backend: CacheBackend | None = None) -> None:
        if backend:
            self._backend = backend
        self._initialized = True

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @staticmethod
    def make_key(func_name: str, args: tuple, kwargs: dict) -> str:
        raw = f"{func_name}:{json.dumps(args, default=str)}:{json.dumps(kwargs, sort_keys=True, default=str)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    async def get(self, key: str) -> Any | None:
        return await self._backend.get(key)

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        await self._backend.set(key, value, ttl)

    async def delete(self, key: str) -> None:
        await self._backend.delete(key)

    async def clear(self) -> None:
        await self._backend.clear()
