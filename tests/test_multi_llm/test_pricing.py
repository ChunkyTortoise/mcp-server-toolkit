"""Tests for pricing estimation."""

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
        # 1M input at $2.00, 1M output at $6.00
        cost = estimate_cost("grok-4.20-0309-non-reasoning", 1_000_000, 1_000_000)
        assert abs(cost - 8.00) < 1e-9

    def test_small_token_count(self):
        # 100 input + 50 output for gpt-4.1-nano
        # input: 100 * 0.10 / 1M = 0.000010
        # output: 50 * 0.40 / 1M = 0.000020
        cost = estimate_cost("gpt-4.1-nano", 100, 50)
        assert abs(cost - 0.000030) < 1e-10

    def test_all_models_in_pricing_table(self):
        expected = {
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.0-flash-lite",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
            "grok-4.20-0309-non-reasoning",
            "grok-4.20-0309-reasoning",
            "grok-4-1-fast-non-reasoning",
        }
        assert set(PRICING.keys()) == expected
