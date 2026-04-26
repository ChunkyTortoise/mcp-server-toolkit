"""Routing tables for cheap and best model selection."""

from __future__ import annotations

from mcp_toolkit.servers.multi_llm.models import ProviderName

# Priority-ordered (provider, model) for cheapest routing
CHEAP_PRIORITY: list[tuple[ProviderName, str]] = [
    (ProviderName.GEMINI, "gemini-2.0-flash-lite"),
    (ProviderName.OPENAI, "gpt-4.1-nano"),
    (ProviderName.XAI, "grok-4-1-fast-non-reasoning"),
]

# Priority-ordered (provider, model) for best quality routing
BEST_PRIORITY: list[tuple[ProviderName, str]] = [
    (ProviderName.OPENAI, "gpt-5.5"),
    (ProviderName.GEMINI, "gemini-2.5-pro"),
    (ProviderName.XAI, "grok-4.20-0309-non-reasoning"),
]
