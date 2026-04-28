"""Per-call LLM cost attribution for MCP tool calls.

CostTracker reads token usage from provider API responses, looks up the
per-model price from mcp_toolkit/pricing/2026.json, and emits ``tool.cost_usd``
as an OTel span attribute.

Usage::

    tracker = CostTracker()
    cost = tracker.record_usage("openai", "gpt-5.5", input_tokens=512, output_tokens=128)
    # cost -> 0.000_002_048 USD

    summary = tracker.summary()
    # {'total_cost_usd': 0.002, 'by_model': {...}, 'total_calls': 5}
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PRICING_FILE = Path(__file__).parent.parent / "pricing" / "2026.json"


def _load_pricing() -> dict[str, dict[str, dict[str, float]]]:
    try:
        data = json.loads(_PRICING_FILE.read_text())
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception as exc:
        logger.warning("Failed to load pricing table (%s); cost attribution disabled.", exc)
        return {}


_PRICING: dict[str, dict[str, dict[str, float]]] = _load_pricing()


@dataclass
class UsageRecord:
    """A single recorded LLM API call with token counts and cost."""

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    tool_name: str = ""


@dataclass
class CostTracker:
    """Accumulates LLM token usage and computes per-call USD costs.

    Thread-safe for reads; writes are not protected — use one tracker per
    request context or per server instance.
    """

    _records: list[UsageRecord] = field(default_factory=list)

    def record_usage(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        tool_name: str = "",
    ) -> float:
        """Record token usage for one API call and return the USD cost.

        Args:
            provider:      Provider key matching pricing table (anthropic, openai, google, xai).
            model:         Model ID (e.g. "gpt-5.5", "claude-sonnet-4-6").
            input_tokens:  Prompt / input token count from the API response.
            output_tokens: Completion / output token count from the API response.
            tool_name:     Optional MCP tool name for attribution.

        Returns:
            Cost in USD for this call.
        """
        cost = self._compute_cost(provider, model, input_tokens, output_tokens)
        self._records.append(
            UsageRecord(
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
                tool_name=tool_name,
            )
        )
        return cost

    def record_from_anthropic_usage(self, usage: Any, model: str, tool_name: str = "") -> float:
        """Record from an Anthropic SDK ``Usage`` object."""
        return self.record_usage(
            provider="anthropic",
            model=model,
            input_tokens=getattr(usage, "input_tokens", 0),
            output_tokens=getattr(usage, "output_tokens", 0),
            tool_name=tool_name,
        )

    def record_from_openai_usage(self, usage: Any, model: str, tool_name: str = "") -> float:
        """Record from an OpenAI ``CompletionUsage`` object."""
        return self.record_usage(
            provider="openai",
            model=model,
            input_tokens=getattr(usage, "prompt_tokens", 0),
            output_tokens=getattr(usage, "completion_tokens", 0),
            tool_name=tool_name,
        )

    def record_from_response_dict(self, response: dict[str, Any], provider: str, model: str, tool_name: str = "") -> float:
        """Record from a raw API response dict (Gemini, xAI, generic)."""
        usage = response.get("usageMetadata") or response.get("usage") or {}
        input_tok = (
            usage.get("promptTokenCount")
            or usage.get("prompt_tokens")
            or usage.get("input_tokens", 0)
        )
        output_tok = (
            usage.get("candidatesTokenCount")
            or usage.get("completion_tokens")
            or usage.get("output_tokens", 0)
        )
        return self.record_usage(
            provider=provider,
            model=model,
            input_tokens=int(input_tok),
            output_tokens=int(output_tok),
            tool_name=tool_name,
        )

    @staticmethod
    def _compute_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
        """Look up price and compute USD cost. Returns 0.0 if model not found."""
        provider_prices = _PRICING.get(provider, {})
        prices = provider_prices.get(model)
        if prices is None:
            # Try fuzzy match: model prefix (e.g. "gpt-5.5-turbo" → "gpt-5.5")
            for key, val in provider_prices.items():
                if model.startswith(key) or key.startswith(model.split("-")[0]):
                    prices = val
                    break
        if prices is None:
            logger.debug("No pricing entry for %s/%s; cost = $0.00", provider, model)
            return 0.0

        cost = (input_tokens / 1_000_000) * prices["input"] + (output_tokens / 1_000_000) * prices["output"]
        return round(cost, 8)

    def total_cost(self) -> float:
        return round(sum(r.cost_usd for r in self._records), 8)

    def cost_by_model(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for r in self._records:
            key = f"{r.provider}/{r.model}"
            totals[key] = round(totals.get(key, 0.0) + r.cost_usd, 8)
        return totals

    def cost_by_tool(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for r in self._records:
            if r.tool_name:
                totals[r.tool_name] = round(totals.get(r.tool_name, 0.0) + r.cost_usd, 8)
        return totals

    def summary(self) -> dict[str, Any]:
        return {
            "total_cost_usd": self.total_cost(),
            "total_calls": len(self._records),
            "total_input_tokens": sum(r.input_tokens for r in self._records),
            "total_output_tokens": sum(r.output_tokens for r in self._records),
            "by_model": self.cost_by_model(),
            "by_tool": self.cost_by_tool(),
        }

    def reset(self) -> None:
        self._records.clear()

    @classmethod
    def price_for(cls, provider: str, model: str) -> dict[str, float] | None:
        """Return the pricing entry for a model, or None if unknown."""
        return _PRICING.get(provider, {}).get(model)
