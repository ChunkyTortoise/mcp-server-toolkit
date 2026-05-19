"""Tests for pricing estimation.

Pricing is derived from the single canonical table (``pricing/2026.json``);
these tests assert the delegation contract and the canonical values, not a
hand-maintained duplicate list.
"""

from __future__ import annotations

import pytest

from mcp_toolkit.servers.multi_llm.pricing import PRICING, estimate_cost


class TestEstimateCost:
    def test_unknown_model_returns_zero(self):
        assert estimate_cost("unknown-model-xyz", 1000, 500) == 0.0

    def test_zero_tokens_returns_zero(self):
        assert estimate_cost("gpt-4.1", 0, 0) == 0.0

    def test_gemini_flash_lite_cost(self):
        # 1M input at $0.075, 1M output at $0.30
        cost = estimate_cost("gemini-2.0-flash-lite", 1_000_000, 1_000_000)
        assert abs(cost - 0.375) < 1e-9

    def test_gpt41_cost(self):
        # 1M input at $2.00, 1M output at $8.00
        cost = estimate_cost("gpt-4.1", 1_000_000, 1_000_000)
        assert abs(cost - 10.00) < 1e-9

    def test_grok4_cost(self):
        # 1M input at $3.00, 1M output at $15.00 (canonical 2026.json: xai)
        cost = estimate_cost("grok-4.20-0309-non-reasoning", 1_000_000, 1_000_000)
        assert abs(cost - 18.00) < 1e-9

    def test_small_token_count(self):
        # 100 input + 50 output for gpt-4.1-nano
        # input: 100 * 0.10 / 1M = 0.000010
        # output: 50 * 0.40 / 1M = 0.000020
        cost = estimate_cost("gpt-4.1-nano", 100, 50)
        assert abs(cost - 0.000030) < 1e-10

    def test_pricing_is_derived_from_canonical_table(self):
        # PRICING must mirror pricing/2026.json exactly — single source of truth.
        from mcp_toolkit.framework.costing import _PRICING as canonical

        expected_models = {
            model for table in canonical.values() for model in table
        }
        assert set(PRICING) == expected_models
        # Spot-check a model resolves to the canonical price.
        assert PRICING["gpt-5.5"] == (2.00, 8.00)

    def test_gpt55_cost(self):
        # 1M input at $2.00, 1M output at $8.00 (canonical 2026.json: openai)
        cost = estimate_cost("gpt-5.5", 1_000_000, 1_000_000)
        assert abs(cost - 10.00) < 1e-9

    def test_gpt55_pro_cost(self):
        # 1M input at $12.00, 1M output at $48.00 (canonical 2026.json: openai)
        cost = estimate_cost("gpt-5.5-pro", 1_000_000, 1_000_000)
        assert abs(cost - 60.00) < 1e-9
