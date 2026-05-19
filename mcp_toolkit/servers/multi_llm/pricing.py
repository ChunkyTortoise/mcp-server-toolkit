"""multi_llm cost estimation.

**Single source of truth:** ``mcp_toolkit/pricing/2026.json``, loaded once by
``mcp_toolkit.framework.costing``. This module exposes a *model-keyed* view of
that canonical table because the multi_llm providers attribute cost by model id
(model ids are unique across providers in the canonical table). There is no
hand-maintained price list here — edit the JSON, not this file.
"""

from __future__ import annotations

# The canonical, already-loaded pricing table (provider -> model -> {input, output}).
# Importing the loaded table (rather than re-reading the JSON) guarantees a single
# in-memory source of truth shared with CostTracker.
from mcp_toolkit.framework.costing import _PRICING as _CANONICAL_PRICING

# Canonical-derived, model-keyed view: {model_id: (input_per_1M, output_per_1M)}.
PRICING: dict[str, tuple[float, float]] = {
    model: (prices["input"], prices["output"])
    for provider_table in _CANONICAL_PRICING.values()
    for model, prices in provider_table.items()
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return estimated USD cost for ``model``. Returns 0.0 for unknown models.

    Canonical pricing source: ``mcp_toolkit/pricing/2026.json``.
    """
    prices = PRICING.get(model)
    if prices is None:
        return 0.0
    input_price, output_price = prices
    return round(
        (input_tokens * input_price + output_tokens * output_price) / 1_000_000, 8
    )
