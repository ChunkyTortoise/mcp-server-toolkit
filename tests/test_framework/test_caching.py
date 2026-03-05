"""Tests for caching module."""

import asyncio

from mcp_toolkit.framework.caching import CacheLayer


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
