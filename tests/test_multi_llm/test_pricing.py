"""Tests for pricing estimation."""

from __future__ import annotations

import pytest

from mcp_toolkit.servers.multi_llm.pricing import PRICING, estimate_cost


class TestEstimateCost:
    def test_unknown_model_returns_zero(self):
        assert estimate_cost("unknown-model-xyz", 1000, 500) == 0.0

    def test_zero_tokens_returns_zero(self):
        assert estimate_cost("gpt-5.4", 0, 0) == 0.0

    def test_gemini_flash_lite_cost(self):
        # 1M input at $0.25, 1M output at $1.50
        cost = estimate_cost("gemini-3.1-flash-lite-preview", 1_000_000, 1_000_000)
        assert abs(cost - 1.75) < 1e-9

    def test_gpt54_cost(self):
        # 1M input at $2.50, 1M output at $15.00
        cost = estimate_cost("gpt-5.4", 1_000_000, 1_000_000)
        assert abs(cost - 17.50) < 1e-9

    def test_grok4_cost(self):
        # 1M input at $3.00, 1M output at $15.00
        cost = estimate_cost("grok-4-0709", 1_000_000, 1_000_000)
        assert abs(cost - 18.00) < 1e-9

    def test_small_token_count(self):
        # 100 input + 50 output for gpt-5.4-nano
        # input: 100 * 0.20 / 1M = 0.000020
        # output: 50 * 1.25 / 1M = 0.0000625
        cost = estimate_cost("gpt-5.4-nano", 100, 50)
        assert abs(cost - 0.0000825) < 1e-10

    def test_all_models_in_pricing_table(self):
        expected = {
            "gemini-3.1-flash-lite-preview",
            "gemini-3.1-pro-preview",
            "gpt-5.4-nano",
            "gpt-5.4-mini",
            "gpt-5.4",
            "grok-4-1-fast-non-reasoning",
            "grok-4-0709",
        }
        assert set(PRICING.keys()) == expected
