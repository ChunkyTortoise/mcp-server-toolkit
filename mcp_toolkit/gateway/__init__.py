"""Streamable HTTP gateway with JWT bearer verification at the transport boundary.

The app is imported lazily: framework.http_auth imports sdk_bridge from this
package, and app imports the framework back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp_toolkit.gateway.app import create_server, main

__all__ = ["create_server", "main"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from mcp_toolkit.gateway import app

        return getattr(app, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
