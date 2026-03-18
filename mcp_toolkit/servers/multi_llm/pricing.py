"""Pricing tables and cost estimation for LLM providers."""

from __future__ import annotations

# Per 1M tokens (input_price_usd, output_price_usd)
PRICING: dict[str, tuple[float, float]] = {
    # Gemini
    "gemini-3.1-flash-lite-preview": (0.25, 1.50),
    "gemini-3.1-pro-preview": (2.00, 12.00),
    # OpenAI
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4": (2.50, 15.00),
    # xAI
    "grok-4-1-fast-non-reasoning": (0.20, 0.50),
    "grok-4-0709": (3.00, 15.00),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return estimated USD cost. Returns 0.0 for unknown models."""
    if model not in PRICING:
        return 0.0
    input_price, output_price = PRICING[model]
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000
