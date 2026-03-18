"""Routing tables for cheap and best model selection."""

from __future__ import annotations

from mcp_toolkit.servers.multi_llm.models import ProviderName

# Priority-ordered (provider, model) for cheapest routing
CHEAP_PRIORITY: list[tuple[ProviderName, str]] = [
    (ProviderName.GEMINI, "gemini-3.1-flash-lite-preview"),
    (ProviderName.OPENAI, "gpt-5.4-nano"),
    (ProviderName.XAI, "grok-4-1-fast-non-reasoning"),
]

# Priority-ordered (provider, model) for best quality routing
BEST_PRIORITY: list[tuple[ProviderName, str]] = [
    (ProviderName.OPENAI, "gpt-5.4"),
    (ProviderName.GEMINI, "gemini-3.1-pro-preview"),
    (ProviderName.XAI, "grok-4-0709"),
]
