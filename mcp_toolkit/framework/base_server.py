"""EnhancedMCP — extends FastMCP with caching, rate limiting, and telemetry."""

from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from mcp_toolkit.framework.caching import CacheLayer, InMemoryCache
from mcp_toolkit.framework.rate_limiter import RateLimiter
from mcp_toolkit.framework.telemetry import TelemetryProvider

logger = logging.getLogger(__name__)


class EnhancedMCP(FastMCP):
    """Enhanced FastMCP with caching, rate limiting, and telemetry.

    All MCP servers in the toolkit inherit from this class to get
    production-grade features out of the box.
    """

    def __init__(self, name: str, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        self._cache = CacheLayer(InMemoryCache())
        self._rate_limiter = RateLimiter()
        self._telemetry = TelemetryProvider(name)
        self._setup_telemetry()
        self._setup_caching()

    def _setup_telemetry(self) -> None:
        self._telemetry.initialize()

    def _setup_caching(self) -> None:
        self._cache.initialize()

    @property
    def cache(self) -> CacheLayer:
        return self._cache

    @property
    def rate_limiter(self) -> RateLimiter:
        return self._rate_limiter

    @property
    def telemetry(self) -> TelemetryProvider:
        return self._telemetry

    def cached_tool(self, ttl: int = 300) -> Callable:
        """Decorator for tools with automatic response caching.

        Usage:
            @mcp.cached_tool(ttl=600)
            async def my_tool(query: str) -> str:
                ...
        """

        def decorator(func: Callable) -> Callable:
            @self.tool()
            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                cache_key = CacheLayer.make_key(func.__name__, args, kwargs)
                t0 = time.monotonic()
                cached = await self._cache.get(cache_key)
                if cached is not None:
                    hit_ms = (time.monotonic() - t0) * 1000
                    self._telemetry.record_tool_call(func.__name__, hit_ms, True, cache_hit=True)
                    return cached
                start = time.monotonic()
                result = await func(*args, **kwargs)
                duration_ms = (time.monotonic() - start) * 1000
                await self._cache.set(cache_key, result, ttl=ttl)
                self._telemetry.record_tool_call(func.__name__, duration_ms, True, cache_hit=False)
                return result

            wrapper.__wrapped__ = func  # type: ignore[attr-defined]
            return wrapper

        return decorator

    def rate_limited_tool(self, max_calls: int = 100, window_seconds: int = 60) -> Callable:
        """Decorator for tools with per-caller rate limiting.

        Usage:
            @mcp.rate_limited_tool(max_calls=10, window_seconds=60)
            async def my_tool(query: str) -> str:
                ...
        """

        def decorator(func: Callable) -> Callable:
            @self.tool()
            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                # Resolve caller identity from tool kwargs. When no identifier
                # is found, fall back to a shared "default" bucket and emit a
                # warning — all unidentified callers share one rate-limit counter,
                # which is usually not the intended behaviour.
                caller_id = (
                    kwargs.get("caller_id")
                    or kwargs.get("client_id")
                    or kwargs.get("user_id")
                )
                if not caller_id:
                    caller_id = "default"
                    logger.warning(
                        "rate_limited_tool(%s): no caller_id/client_id/user_id in kwargs; "
                        "all unidentified callers share a single rate-limit bucket. "
                        "Pass one of those kwargs to get per-caller limiting.",
                        func.__name__,
                    )
                rate_key = f"{func.__name__}:{caller_id}"
                allowed = await self._rate_limiter.check(
                    key=rate_key,
                    max_calls=max_calls,
                    window=window_seconds,
                )
                if not allowed:
                    return f"Error: Rate limit exceeded. Retry after {window_seconds} seconds."
                start = time.monotonic()
                result = await func(*args, **kwargs)
                duration_ms = (time.monotonic() - start) * 1000
                self._telemetry.record_tool_call(func.__name__, duration_ms, True)
                return result

            wrapper.__wrapped__ = func  # type: ignore[attr-defined]
            return wrapper

        return decorator

    def auth_tool(self, auth: Any, required_scope: str = "") -> Callable:
        """Decorator for tools requiring authentication and optional scope.

        Combines ``@mcp.tool()`` with ``@requires_scope(auth, scope)``. The
        tool function must accept a ``token`` or ``api_key`` kwarg.

        Usage::

            @mcp.auth_tool(jwt_auth, required_scope="db:read")
            async def query_database(sql: str, token: str = "") -> str:
                ...
        """
        from mcp_toolkit.framework.auth import requires_scope

        def decorator(func: Callable) -> Callable:
            @self.tool()
            @requires_scope(auth, required_scope)
            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                return await func(*args, **kwargs)

            wrapper.__wrapped__ = func  # type: ignore[attr-defined]
            return wrapper

        return decorator
