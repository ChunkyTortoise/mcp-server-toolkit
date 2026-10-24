"""EnhancedMCP: extends FastMCP with caching, rate limiting, and telemetry."""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from mcp_toolkit.framework.auth import _audit
from mcp_toolkit.framework.caching import CacheLayer, InMemoryCache
from mcp_toolkit.framework.errors import RateLimited
from mcp_toolkit.framework.rate_limiter import RateLimiter
from mcp_toolkit.framework.telemetry import TelemetryProvider

logger = logging.getLogger(__name__)


class EnhancedMCP(FastMCP):
    """Enhanced FastMCP with caching, rate limiting, and telemetry.

    All MCP servers in the toolkit inherit from this class. The decorators
    forward extra keyword arguments (name, title, description, annotations, icons,
    meta, structured_output) to ``FastMCP.tool``. Each decorated call records one
    span. Refusals raise ``ToolError`` subclasses, so clients receive ``isError``.
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

    def _register_tool(self, func: Callable, wrapper: Callable, tool_kwargs: dict[str, Any]) -> Callable:
        """Register ``wrapper`` with FastMCP, refusing a name that is already taken.

        FastMCP keeps the first registration and drops later ones silently, so
        stacking two toolkit decorators would lose the outer guard without a sound.
        """
        name = tool_kwargs.get("name") or func.__name__
        if self._tool_manager.get_tool(name) is not None:
            raise ValueError(
                f"Tool {name!r} is already registered. Stacked toolkit decorators or "
                "a repeated name would silently drop one guard; register each tool once."
            )
        return self.tool(**tool_kwargs)(wrapper)

    def cached_tool(self, ttl: int = 300, **tool_kwargs: Any) -> Callable:
        """Decorator for tools with automatic response caching.

        Usage:
            @mcp.cached_tool(ttl=600)
            async def my_tool(query: str) -> str:
                ...

        Extra keyword arguments (``name``, ``annotations``, ``structured_output``...)
        go to ``FastMCP.tool``.
        """

        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                async with self._telemetry.tool_call(func.__name__) as call:
                    cache_key = CacheLayer.make_key(func.__name__, args, kwargs)
                    cached = await self._cache.get(cache_key)
                    if cached is not None:
                        call["cache_hit"] = True
                        return cached
                    call["cache_hit"] = False
                    result = await func(*args, **kwargs)
                    await self._cache.set(cache_key, result, ttl=ttl)
                    return result

            wrapper.__wrapped__ = func  # type: ignore[attr-defined]
            return self._register_tool(func, wrapper, tool_kwargs)

        return decorator

    def rate_limited_tool(
        self, max_calls: int = 100, window_seconds: int = 60, **tool_kwargs: Any
    ) -> Callable:
        """Decorator for tools with per-caller rate limiting.

        Usage:
            @mcp.rate_limited_tool(max_calls=10, window_seconds=60)
            async def my_tool(query: str) -> str:
                ...
        """

        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                async with self._telemetry.tool_call(func.__name__):
                    # Resolve caller identity from tool kwargs. When no identifier
                    # is found, fall back to a shared "default" bucket and emit a
                    # warning: all unidentified callers share one rate-limit counter,
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
                        _audit(
                            "rate_limit.rejected",
                            tool=func.__name__,
                            caller=str(caller_id),
                            max_calls=max_calls,
                            window_seconds=window_seconds,
                        )
                        raise RateLimited(f"Rate limited: retry after {window_seconds}s")
                    return await func(*args, **kwargs)

            wrapper.__wrapped__ = func  # type: ignore[attr-defined]
            return self._register_tool(func, wrapper, tool_kwargs)

        return decorator

    def auth_tool(self, auth: Any, required_scope: str = "", **tool_kwargs: Any) -> Callable:
        """Decorator for tools requiring authentication and optional scope.

        Combines ``@mcp.tool()`` with ``@requires_scope(auth, scope)``. The
        tool function must accept a ``token`` or ``api_key`` kwarg. A refusal
        raises ``Unauthorized`` or ``Forbidden`` and the tool body never runs.
        Extra keyword arguments go to ``FastMCP.tool``.

        Usage::

            @mcp.auth_tool(jwt_auth, required_scope="db:read")
            async def query_database(sql: str, token: str = "") -> str:
                ...
        """
        from mcp_toolkit.framework.auth import requires_scope

        def decorator(func: Callable) -> Callable:
            guarded = requires_scope(auth, required_scope)(func)

            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                async with self._telemetry.tool_call(func.__name__):
                    return await guarded(*args, **kwargs)

            wrapper.__wrapped__ = func  # type: ignore[attr-defined]
            return self._register_tool(func, wrapper, tool_kwargs)

        return decorator
