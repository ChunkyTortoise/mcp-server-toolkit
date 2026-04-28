"""Tests for CostTracker — pricing lookup, usage recording, aggregation."""

from __future__ import annotations

import pytest

from mcp_toolkit.framework.costing import CostTracker


class TestCostComputation:
    def test_known_model_cost(self):
        cost = CostTracker._compute_cost("openai", "gpt-5.5", input_tokens=1_000_000, output_tokens=0)
        assert cost == pytest.approx(2.00, rel=1e-3)

    def test_output_tokens_priced_higher(self):
        input_cost = CostTracker._compute_cost("openai", "gpt-5.5", 1_000_000, 0)
        output_cost = CostTracker._compute_cost("openai", "gpt-5.5", 0, 1_000_000)
        assert output_cost > input_cost

    def test_unknown_model_returns_zero(self):
        cost = CostTracker._compute_cost("openai", "nonexistent-model-xyz", 100_000, 50_000)
        assert cost == 0.0

    def test_unknown_provider_returns_zero(self):
        cost = CostTracker._compute_cost("mystery-provider", "some-model", 100_000, 50_000)
        assert cost == 0.0

    def test_anthropic_haiku_cheapest(self):
        haiku = CostTracker._compute_cost("anthropic", "claude-haiku-4-5-20251001", 1_000_000, 1_000_000)
        sonnet = CostTracker._compute_cost("anthropic", "claude-sonnet-4-6", 1_000_000, 1_000_000)
        opus = CostTracker._compute_cost("anthropic", "claude-opus-4-7", 1_000_000, 1_000_000)
        assert haiku < sonnet < opus

    def test_gemini_flash_lite_cheapest_google(self):
        lite = CostTracker._compute_cost("google", "gemini-2.0-flash-lite", 1_000_000, 1_000_000)
        pro = CostTracker._compute_cost("google", "gemini-2.5-pro", 1_000_000, 1_000_000)
        assert lite < pro

    def test_small_call_cost_is_fractional(self):
        cost = CostTracker._compute_cost("openai", "gpt-5.5", input_tokens=500, output_tokens=200)
        assert 0 < cost < 0.01

    def test_price_for_returns_dict(self):
        p = CostTracker.price_for("anthropic", "claude-sonnet-4-6")
        assert p is not None
        assert "input" in p and "output" in p

    def test_price_for_unknown_returns_none(self):
        assert CostTracker.price_for("openai", "gpt-3") is None


class TestCostTrackerRecording:
    def test_record_usage_returns_cost(self):
        t = CostTracker()
        cost = t.record_usage("openai", "gpt-5.5", input_tokens=10_000, output_tokens=2_000)
        assert cost > 0

    def test_total_cost_accumulates(self):
        t = CostTracker()
        c1 = t.record_usage("openai", "gpt-5.5", 10_000, 2_000)
        c2 = t.record_usage("anthropic", "claude-sonnet-4-6", 5_000, 1_000)
        assert t.total_cost() == pytest.approx(c1 + c2, rel=1e-6)

    def test_cost_by_model(self):
        t = CostTracker()
        t.record_usage("openai", "gpt-5.5", 10_000, 2_000, tool_name="query")
        t.record_usage("openai", "gpt-5.5", 5_000, 1_000, tool_name="query")
        by_model = t.cost_by_model()
        assert "openai/gpt-5.5" in by_model
        assert by_model["openai/gpt-5.5"] > 0

    def test_cost_by_tool(self):
        t = CostTracker()
        t.record_usage("openai", "gpt-5.5", 10_000, 2_000, tool_name="tool_a")
        t.record_usage("anthropic", "claude-sonnet-4-6", 5_000, 1_000, tool_name="tool_b")
        by_tool = t.cost_by_tool()
        assert "tool_a" in by_tool
        assert "tool_b" in by_tool

    def test_summary_structure(self):
        t = CostTracker()
        t.record_usage("openai", "gpt-5.5", 1_000, 200)
        s = t.summary()
        assert "total_cost_usd" in s
        assert "total_calls" in s
        assert "by_model" in s
        assert s["total_calls"] == 1

    def test_reset_clears_all(self):
        t = CostTracker()
        t.record_usage("openai", "gpt-5.5", 10_000, 2_000)
        t.reset()
        assert t.total_cost() == 0.0
        assert t.summary()["total_calls"] == 0

    def test_record_from_anthropic_usage(self):
        from unittest.mock import MagicMock
        usage = MagicMock()
        usage.input_tokens = 500
        usage.output_tokens = 100
        t = CostTracker()
        cost = t.record_from_anthropic_usage(usage, "claude-sonnet-4-6", tool_name="my_tool")
        assert cost > 0
        assert t.cost_by_tool()["my_tool"] > 0

    def test_record_from_openai_usage(self):
        from unittest.mock import MagicMock
        usage = MagicMock()
        usage.prompt_tokens = 800
        usage.completion_tokens = 200
        t = CostTracker()
        cost = t.record_from_openai_usage(usage, "gpt-5.5")
        assert cost > 0

    def test_record_from_response_dict_gemini(self):
        response = {"usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 300}}
        t = CostTracker()
        cost = t.record_from_response_dict(response, "google", "gemini-2.5-pro")
        assert cost > 0

    def test_zero_tokens_zero_cost(self):
        t = CostTracker()
        cost = t.record_usage("openai", "gpt-5.5", 0, 0)
        assert cost == 0.0
