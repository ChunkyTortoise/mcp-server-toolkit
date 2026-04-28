"""Tests for caching module."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_toolkit.framework.caching import CacheLayer, InMemoryCache, RedisCache


class TestInMemoryCache:
    async def test_set_and_get(self, cache):
        await cache.set("key1", "value1")
        result = await cache.get("key1")
        assert result == "value1"

    async def test_get_missing_key(self, cache):
        result = await cache.get("nonexistent")
        assert result is None

    async def test_delete(self, cache):
        await cache.set("key1", "value1")
        await cache.delete("key1")
        result = await cache.get("key1")
        assert result is None

    async def test_clear(self, cache):
        await cache.set("k1", "v1")
        await cache.set("k2", "v2")
        await cache.clear()
        assert cache.size == 0

    async def test_ttl_expiry(self, cache):
        await cache.set("temp", "data", ttl=0)
        await asyncio.sleep(0.01)
        result = await cache.get("temp")
        assert result is None

    async def test_stores_complex_types(self, cache):
        data = {"list": [1, 2, 3], "nested": {"a": True}}
        await cache.set("complex", data)
        result = await cache.get("complex")
        assert result == data

    async def test_size_property(self, cache):
        assert cache.size == 0
        await cache.set("k1", "v1")
        assert cache.size == 1
        await cache.set("k2", "v2")
        assert cache.size == 2

    async def test_delete_nonexistent_no_error(self, cache):
        await cache.delete("ghost")  # should not raise


class TestCacheLayer:
    async def test_set_and_get(self, cache_layer):
        await cache_layer.set("test", "value", ttl=60)
        result = await cache_layer.get("test")
        assert result == "value"

    async def test_make_key_deterministic(self):
        k1 = CacheLayer.make_key("func", (1, 2), {"a": "b"})
        k2 = CacheLayer.make_key("func", (1, 2), {"a": "b"})
        assert k1 == k2

    async def test_make_key_different_for_different_args(self):
        k1 = CacheLayer.make_key("func", (1,), {})
        k2 = CacheLayer.make_key("func", (2,), {})
        assert k1 != k2

    async def test_is_initialized(self):
        layer = CacheLayer()
        assert layer.is_initialized is False
        layer.initialize()
        assert layer.is_initialized is True

    async def test_delete(self, cache_layer):
        await cache_layer.set("del-me", "data")
        await cache_layer.delete("del-me")
        result = await cache_layer.get("del-me")
        assert result is None

    async def test_clear(self, cache_layer):
        await cache_layer.set("a", 1)
        await cache_layer.set("b", 2)
        await cache_layer.clear()
        assert await cache_layer.get("a") is None
        assert await cache_layer.get("b") is None


class TestRedisCache:
    def _make_mock_redis(self, ping_ok: bool = True) -> MagicMock:
        """Build a mock Redis client with async methods."""
        client = MagicMock()
        client.ping = AsyncMock(return_value=True if ping_ok else (_ for _ in ()).throw(Exception("refused")))
        client.get = AsyncMock(return_value=None)
        client.setex = AsyncMock(return_value=True)
        client.delete = AsyncMock(return_value=1)
        client.keys = AsyncMock(return_value=[])
        return client

    async def test_get_miss_returns_none(self):
        cache = RedisCache()
        mock_client = self._make_mock_redis()
        mock_client.get = AsyncMock(return_value=None)
        cache._client = mock_client
        result = await cache.get("missing")
        assert result is None

    async def test_set_and_get_roundtrip(self):
        cache = RedisCache()
        mock_client = self._make_mock_redis()
        stored: dict = {}

        async def fake_setex(key, ttl, value):
            stored[key] = value

        async def fake_get(key):
            return stored.get(key)

        mock_client.setex = fake_setex
        mock_client.get = fake_get
        cache._client = mock_client

        await cache.set("foo", {"x": 1}, ttl=60)
        result = await cache.get("foo")
        assert result == {"x": 1}

    async def test_set_prefixes_key_with_mcp(self):
        cache = RedisCache()
        mock_client = self._make_mock_redis()
        seen_keys: list = []

        async def capture_setex(key, ttl, value):
            seen_keys.append(key)

        mock_client.setex = capture_setex
        cache._client = mock_client

        await cache.set("mykey", "value")
        assert seen_keys[0] == "mcp:mykey"

    async def test_delete_calls_redis(self):
        cache = RedisCache()
        mock_client = self._make_mock_redis()
        deleted: list = []

        async def capture_delete(*keys):
            deleted.extend(keys)

        mock_client.delete = capture_delete
        cache._client = mock_client

        await cache.delete("target")
        assert "mcp:target" in deleted

    async def test_clear_deletes_all_mcp_keys(self):
        cache = RedisCache()
        mock_client = self._make_mock_redis()
        mock_client.keys = AsyncMock(return_value=["mcp:a", "mcp:b"])
        deleted: list = []

        async def capture_delete(*keys):
            deleted.extend(keys)

        mock_client.delete = capture_delete
        cache._client = mock_client

        await cache.clear()
        assert "mcp:a" in deleted
        assert "mcp:b" in deleted

    async def test_clear_with_no_keys_is_safe(self):
        cache = RedisCache()
        mock_client = self._make_mock_redis()
        mock_client.keys = AsyncMock(return_value=[])
        cache._client = mock_client
        await cache.clear()  # should not raise

    async def test_falls_back_to_memory_when_redis_unavailable(self):
        cache = RedisCache(redis_url="redis://nonexistent:9999", fallback_to_memory=True)
        # _get_client will fail; fallback to in-memory
        await cache.set("fallback_key", "fallback_value")
        result = await cache.get("fallback_key")
        assert result == "fallback_value"

    async def test_get_falls_back_to_memory_on_redis_error(self):
        cache = RedisCache(fallback_to_memory=True)
        mock_client = self._make_mock_redis()

        async def raise_on_get(key):
            raise ConnectionError("Redis down")

        mock_client.get = raise_on_get
        cache._client = mock_client
        # Should not raise; falls back to in-memory (returns None since not set there)
        result = await cache.get("any_key")
        assert result is None

    async def test_set_falls_back_to_memory_on_redis_error(self):
        cache = RedisCache(fallback_to_memory=True)
        mock_client = self._make_mock_redis()

        async def raise_on_setex(*args):
            raise ConnectionError("Redis down")

        mock_client.setex = raise_on_setex
        cache._client = mock_client
        # Should not raise; data written to in-memory fallback
        await cache.set("fb_key", "fb_value")
        result = await cache._fallback.get("fb_key")
        assert result == "fb_value"

    async def test_strict_mode_raises_on_connection_error(self):
        cache = RedisCache()  # fallback_to_memory=False by default
        mock_client = self._make_mock_redis()

        async def raise_on_get(key):
            raise ConnectionError("Redis down")

        mock_client.get = raise_on_get
        cache._client = mock_client
        with pytest.raises(ConnectionError):
            await cache.get("any_key")

    async def test_get_parses_json_from_redis(self):
        cache = RedisCache()
        mock_client = self._make_mock_redis()
        mock_client.get = AsyncMock(return_value=json.dumps({"answer": 42}))
        cache._client = mock_client
        result = await cache.get("jsonkey")
        assert result == {"answer": 42}
