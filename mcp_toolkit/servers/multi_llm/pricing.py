"""Pricing tables and cost estimation for LLM providers."""

from __future__ import annotations

# Per 1M tokens (input_price_usd, output_price_usd)
PRICING: dict[str, tuple[float, float]] = {
    # Gemini
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.0-flash-lite": (0.075, 0.30),
    # OpenAI
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    # xAI
    "grok-4.20-0309-non-reasoning": (2.00, 6.00),
    "grok-4.20-0309-reasoning": (2.00, 6.00),
    "grok-4-1-fast-non-reasoning": (0.20, 0.50),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return estimated USD cost. Returns 0.0 for unknown models."""
    if model not in PRICING:
        return 0.0
    input_price, output_price = PRICING[model]
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000
