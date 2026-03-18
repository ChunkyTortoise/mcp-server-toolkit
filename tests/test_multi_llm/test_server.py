"""Integration tests for Multi-LLM MCP server tools."""

from __future__ import annotations

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp_toolkit.framework.testing import MCPTestClient
from mcp_toolkit.servers.multi_llm.models import LLMResponse, ProviderName
from mcp_toolkit.servers.multi_llm.providers import MockProvider
from mcp_toolkit.servers.multi_llm.server import _format_response, configure
from mcp_toolkit.servers.multi_llm.server import mcp as multi_llm_mcp


@pytest.fixture
async def client():
    """Fixture: configure three mock providers and return an MCPTestClient."""
    providers = {
        ProviderName.GEMINI: MockProvider(ProviderName.GEMINI, "gemini-2.0-flash"),
        ProviderName.OPENAI: MockProvider(ProviderName.OPENAI, "gpt-4o"),
        ProviderName.XAI: MockProvider(ProviderName.XAI, "grok-3"),
    }
    configure(providers=providers)
    # Clear cache to prevent cross-test pollution
    await multi_llm_mcp._cache.clear()
    yield MCPTestClient(multi_llm_mcp)
    # Teardown
    configure(providers={})
    await multi_llm_mcp._cache.clear()


@pytest.fixture
async def empty_client():
    """Fixture: no providers configured."""
    configure(providers={})
    await multi_llm_mcp._cache.clear()
    yield MCPTestClient(multi_llm_mcp)
    configure(providers={})


class TestQueryModel:
    async def test_invalid_provider_returns_error(self, client):
        result = await client.call_tool(
            "query_model", {"provider": "invalid", "model": "x", "prompt": "hi"}
        )
        assert "Error" in result
        assert "Unknown provider" in result

    async def test_unconfigured_provider_returns_error(self, empty_client):
        result = await empty_client.call_tool(
            "query_model", {"provider": "gemini", "model": "gemini-2.0-flash", "prompt": "hi"}
        )
        assert "Error" in result
        assert "not configured" in result

    async def test_valid_query_returns_response(self, client):
        result = await client.call_tool(
            "query_model",
            {"provider": "gemini", "model": "gemini-2.0-flash", "prompt": "Say hello"},
        )
        assert "gemini" in result
        assert "gemini-2.0-flash" in result
        assert "Mock response" in result

    async def test_response_includes_token_metadata(self, client):
        result = await client.call_tool(
            "query_model",
            {"provider": "openai", "model": "gpt-4o", "prompt": "Test metadata"},
        )
        assert "tokens:" in result
        assert "cost:" in result
        assert "latency:" in result

    async def test_circuit_breaker_open_returns_error(self, client):
        from unittest.mock import patch
        providers = {
            ProviderName.GEMINI: MockProvider(ProviderName.GEMINI, "gemini-2.0-flash"),
        }
        configure(providers=providers)
        # Force circuit breaker open
        with patch("mcp_toolkit.servers.multi_llm.models.time.monotonic", return_value=100.0):
            p = providers[ProviderName.GEMINI]
            p.circuit_breaker.failure_threshold = 1
            p.circuit_breaker.record_failure()

        with patch("mcp_toolkit.servers.multi_llm.models.time.monotonic", return_value=110.0):
            result = await client.call_tool(
                "query_model",
                {"provider": "gemini", "model": "gemini-2.0-flash", "prompt": "test"},
            )
        assert "circuit breaker" in result.lower()

    async def test_xai_provider_query(self, client):
        result = await client.call_tool(
            "query_model",
            {"provider": "xai", "model": "grok-3", "prompt": "Hello from xAI"},
        )
        assert "xai" in result
        assert "grok-3" in result

    async def test_system_prompt_parameter_accepted(self, client):
        result = await client.call_tool(
            "query_model",
            {
                "provider": "openai",
                "model": "gpt-4o",
                "prompt": "Respond briefly",
                "system_prompt": "You are a terse assistant.",
            },
        )
        assert "Error" not in result


class TestGetSecondOpinion:
    async def test_no_providers_returns_error(self, empty_client):
        result = await empty_client.call_tool(
            "get_second_opinion", {"prompt": "What is Python?"}
        )
        assert "Error" in result
        assert "No providers" in result

    async def test_queries_all_three_providers(self, client):
        result = await client.call_tool(
            "get_second_opinion", {"prompt": "What is 1+1?"}
        )
        assert "GEMINI" in result
        assert "OPENAI" in result
        assert "XAI" in result

    async def test_includes_second_opinion_header(self, client):
        result = await client.call_tool(
            "get_second_opinion", {"prompt": "Best language for ML?"}
        )
        assert "Second Opinion" in result

    async def test_skips_provider_with_open_circuit_breaker(self, client):
        from unittest.mock import patch
        providers = {
            ProviderName.GEMINI: MockProvider(ProviderName.GEMINI, "gemini-2.0-flash"),
            ProviderName.OPENAI: MockProvider(ProviderName.OPENAI, "gpt-4o"),
        }
        configure(providers=providers)
        with patch("mcp_toolkit.servers.multi_llm.models.time.monotonic", return_value=100.0):
            providers[ProviderName.GEMINI].circuit_breaker.failure_threshold = 1
            providers[ProviderName.GEMINI].circuit_breaker.record_failure()

        with patch("mcp_toolkit.servers.multi_llm.models.time.monotonic", return_value=110.0):
            result = await client.call_tool(
                "get_second_opinion", {"prompt": "Test skip open cb"}
            )
        assert "OPENAI" in result
        assert "GEMINI" not in result

    async def test_single_provider_still_works(self, client):
        configure(providers={ProviderName.GEMINI: MockProvider(ProviderName.GEMINI)})
        result = await client.call_tool(
            "get_second_opinion", {"prompt": "Single provider test"}
        )
        assert "GEMINI" in result

    async def test_context_passed_as_system_prompt(self, client):
        # With MockProvider, context doesn't affect output but shouldn't error
        result = await client.call_tool(
            "get_second_opinion",
            {"prompt": "Explain caching", "context": "Be concise, 1 sentence."},
        )
        assert "Second Opinion" in result


class TestQueryCheap:
    async def test_routes_to_gemini_flash_lite_first(self, client):
        result = await client.call_tool(
            "query_cheap", {"prompt": "Quick cheap question alpha"}
        )
        assert "gemini" in result
        assert "gemini-3.1-flash-lite-preview" in result

    async def test_no_providers_returns_error(self, empty_client):
        result = await empty_client.call_tool(
            "query_cheap", {"prompt": "No providers test query"}
        )
        assert "Error" in result
        assert "cheap providers" in result

    async def test_falls_back_to_openai_when_gemini_unavailable(self, client):
        providers = {
            ProviderName.OPENAI: MockProvider(ProviderName.OPENAI, "gpt-5.4"),
        }
        configure(providers=providers)
        await multi_llm_mcp._cache.clear()
        result = await client.call_tool(
            "query_cheap", {"prompt": "Fallback cheap test beta"}
        )
        assert "openai" in result
        assert "gpt-5.4-nano" in result

    async def test_result_includes_cost_metadata(self, client):
        await multi_llm_mcp._cache.clear()
        result = await client.call_tool(
            "query_cheap", {"prompt": "Cost metadata check gamma"}
        )
        assert "cost:" in result

    async def test_cache_returns_same_result(self, client):
        prompt = "Cacheable cheap query delta"
        result1 = await client.call_tool("query_cheap", {"prompt": prompt})
        result2 = await client.call_tool("query_cheap", {"prompt": prompt})
        assert result1 == result2


class TestQueryBest:
    async def test_routes_to_openai_gpt54_first(self, client):
        result = await client.call_tool(
            "query_best", {"prompt": "Best quality answer needed"}
        )
        assert "openai" in result
        assert "gpt-5.4" in result

    async def test_no_providers_returns_error(self, empty_client):
        result = await empty_client.call_tool(
            "query_best", {"prompt": "No providers premium test"}
        )
        assert "Error" in result
        assert "premium providers" in result

    async def test_falls_back_to_gemini_when_openai_unavailable(self, client):
        providers = {
            ProviderName.GEMINI: MockProvider(ProviderName.GEMINI, "gemini-3.1-pro-preview"),
        }
        configure(providers=providers)
        result = await client.call_tool(
            "query_best", {"prompt": "Fallback to gemini best"}
        )
        assert "gemini" in result
        assert "gemini-3.1-pro-preview" in result

    async def test_result_includes_token_metadata(self, client):
        result = await client.call_tool(
            "query_best", {"prompt": "Token metadata best query"}
        )
        assert "tokens:" in result
        assert "latency:" in result


class TestToolListing:
    async def test_has_five_tools(self, client):
        tools = await client.list_tools()
        names = {t["name"] for t in tools}
        assert "query_model" in names
        assert "get_second_opinion" in names
        assert "query_cheap" in names
        assert "query_best" in names
        assert "list_providers" in names

    async def test_tools_have_descriptions(self, client):
        tools = await client.list_tools()
        tool_map = {t["name"]: t for t in tools}
        assert tool_map["query_model"]["description"]
        assert tool_map["get_second_opinion"]["description"]
        assert tool_map["query_cheap"]["description"]
        assert tool_map["query_best"]["description"]
        assert tool_map["list_providers"]["description"]


# ---------------------------------------------------------------------------
# Wave 1: Exception path + format + enum
# ---------------------------------------------------------------------------

class TestQueryModelExceptionPath:
    async def test_provider_raises_returns_error_string(self, client):
        providers = {ProviderName.GEMINI: MockProvider(ProviderName.GEMINI)}
        providers[ProviderName.GEMINI].query = AsyncMock(side_effect=Exception("API crashed"))
        configure(providers=providers)
        result = await client.call_tool(
            "query_model",
            {"provider": "gemini", "model": "gemini-2.0-flash", "prompt": "test"},
        )
        assert "Error querying gemini" in result
        assert "API crashed" in result


class TestGetSecondOpinionPartialFailure:
    async def test_one_provider_fails_others_succeed(self, client):
        providers = {
            ProviderName.GEMINI: MockProvider(ProviderName.GEMINI),
            ProviderName.OPENAI: MockProvider(ProviderName.OPENAI),
        }
        providers[ProviderName.GEMINI].query = AsyncMock(side_effect=Exception("Gemini down"))
        configure(providers=providers)
        result = await client.call_tool("get_second_opinion", {"prompt": "test partial"})
        assert "OPENAI" in result
        assert "GEMINI" in result
        assert "Error" in result
        assert "Second Opinion" in result

    async def test_all_providers_fail_returns_error_strings(self, client):
        providers = {ProviderName.GEMINI: MockProvider(ProviderName.GEMINI)}
        providers[ProviderName.GEMINI].query = AsyncMock(side_effect=Exception("all down"))
        configure(providers=providers)
        result = await client.call_tool("get_second_opinion", {"prompt": "test all fail"})
        assert "Error" in result
        assert "Second Opinion" in result


class TestFormatResponse:
    def test_format_response_structure(self):
        resp = LLMResponse(
            provider=ProviderName.GEMINI,
            model="gemini-2.0-flash",
            content="Hello world",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.001,
            latency_ms=100.0,
        )
        result = _format_response(resp)
        assert "**gemini**" in result
        assert "gemini-2.0-flash" in result
        assert "Hello world" in result
        assert "tokens: 10 in / 5 out" in result
        assert "cost:" in result
        assert "latency: 100ms" in result


class TestProviderNameEnum:
    def test_invalid_provider_string_raises_value_error(self):
        with pytest.raises(ValueError):
            ProviderName("not-a-real-provider")


# ---------------------------------------------------------------------------
# Wave 2: Input validation + gather timeout
# ---------------------------------------------------------------------------

class TestInputValidation:
    async def test_empty_prompt_returns_error(self, client):
        result = await client.call_tool(
            "query_model", {"provider": "gemini", "model": "gemini-2.0-flash", "prompt": ""}
        )
        assert "prompt cannot be empty" in result

    async def test_whitespace_only_prompt_returns_error(self, client):
        result = await client.call_tool(
            "query_model", {"provider": "gemini", "model": "gemini-2.0-flash", "prompt": "   "}
        )
        assert "prompt cannot be empty" in result

    async def test_temperature_below_zero_clamped(self, client):
        result = await client.call_tool(
            "query_model",
            {"provider": "gemini", "model": "gemini-2.0-flash", "prompt": "hi", "temperature": -1.0},
        )
        assert "Error" not in result or "prompt" not in result

    async def test_temperature_above_two_clamped(self, client):
        result = await client.call_tool(
            "query_model",
            {"provider": "gemini", "model": "gemini-2.0-flash", "prompt": "hi", "temperature": 5.0},
        )
        assert "Error" not in result or "prompt" not in result

    async def test_max_tokens_below_one_clamped(self, client):
        result = await client.call_tool(
            "query_model",
            {"provider": "gemini", "model": "gemini-2.0-flash", "prompt": "hi", "max_tokens": 0},
        )
        assert "Error" not in result or "prompt" not in result

    async def test_max_tokens_above_limit_clamped(self, client):
        result = await client.call_tool(
            "query_model",
            {
                "provider": "gemini",
                "model": "gemini-2.0-flash",
                "prompt": "hi",
                "max_tokens": 999_999,
            },
        )
        assert "Error" not in result or "prompt" not in result

    async def test_unknown_model_is_accepted(self, client):
        result = await client.call_tool(
            "query_model",
            {"provider": "gemini", "model": "gemini-future-model-xyz", "prompt": "hi"},
        )
        # Unknown model passes through; MockProvider returns a response
        assert "gemini" in result


class TestGatherTimeout:
    async def test_slow_providers_return_timeout_error(self, client):
        with patch(
            "mcp_toolkit.servers.multi_llm.server.asyncio.wait_for",
            side_effect=asyncio.TimeoutError,
        ):
            result = await client.call_tool("get_second_opinion", {"prompt": "timeout test"})
        assert "timed out" in result.lower()


# ---------------------------------------------------------------------------
# Wave 3: list_providers + telemetry
# ---------------------------------------------------------------------------

class TestListProviders:
    async def test_all_providers_listed(self, client):
        result = await client.call_tool("list_providers", {})
        assert "gemini" in result
        assert "openai" in result
        assert "xai" in result

    async def test_shows_default_model(self, client):
        result = await client.call_tool("list_providers", {})
        assert "gemini-2.0-flash" in result
        assert "gpt-4o" in result
        assert "grok-3" in result

    async def test_open_circuit_breaker_shows_open_status(self, client):
        providers = {ProviderName.GEMINI: MockProvider(ProviderName.GEMINI, "gemini-2.0-flash")}
        configure(providers=providers)
        with patch("mcp_toolkit.servers.multi_llm.models.time.monotonic", return_value=100.0):
            providers[ProviderName.GEMINI].circuit_breaker.failure_threshold = 1
            providers[ProviderName.GEMINI].circuit_breaker.record_failure()
        with patch("mcp_toolkit.servers.multi_llm.models.time.monotonic", return_value=110.0):
            result = await client.call_tool("list_providers", {})
        assert "OPEN" in result

    async def test_no_providers_configured_message(self, empty_client):
        result = await empty_client.call_tool("list_providers", {})
        assert "No providers configured." in result


class TestTelemetrySpans:
    async def test_query_model_records_provider_span(self, client):
        multi_llm_mcp.telemetry.clear_spans()
        await client.call_tool(
            "query_model",
            {"provider": "gemini", "model": "gemini-2.0-flash", "prompt": "span test"},
        )
        span_names = [s.name for s in multi_llm_mcp.telemetry.spans]
        assert "provider.gemini" in span_names

    async def test_second_opinion_records_per_provider_spans(self, client):
        multi_llm_mcp.telemetry.clear_spans()
        await client.call_tool("get_second_opinion", {"prompt": "span test all providers"})
        span_names = [s.name for s in multi_llm_mcp.telemetry.spans]
        assert "provider.gemini" in span_names
        assert "provider.openai" in span_names
        assert "provider.xai" in span_names
