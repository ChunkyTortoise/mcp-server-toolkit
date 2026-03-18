"""Tests for LLM provider implementations."""

from __future__ import annotations

import os

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp_toolkit.servers.multi_llm.models import CircuitBreaker, LLMResponse, ProviderName
from mcp_toolkit.servers.multi_llm.providers import (
    GeminiProvider,
    LLMProvider,
    MockProvider,
    OpenAICompatibleProvider,
)


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker()
        assert not cb.is_open()

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert not cb.is_open()
        cb.record_failure()
        assert cb.is_open()

    def test_success_resets_failures(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_success()
        assert cb._failures == 0
        assert not cb.is_open()

    def test_auto_resets_after_cooldown(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=10)
        with patch("mcp_toolkit.servers.multi_llm.models.time.monotonic", return_value=100.0):
            cb.record_failure()
        assert cb._open_until > 0
        with patch("mcp_toolkit.servers.multi_llm.models.time.monotonic", return_value=111.0):
            assert not cb.is_open()
        assert cb._failures == 0

    def test_stays_open_during_cooldown(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=60)
        with patch("mcp_toolkit.servers.multi_llm.models.time.monotonic", return_value=100.0):
            cb.record_failure()
        with patch("mcp_toolkit.servers.multi_llm.models.time.monotonic", return_value=150.0):
            assert cb.is_open()


class TestMockProvider:
    async def test_query_returns_llm_response(self):
        p = MockProvider(ProviderName.GEMINI, "gemini-2.0-flash")
        resp = await p.query("hello world")
        assert isinstance(resp, LLMResponse)
        assert resp.provider == ProviderName.GEMINI
        assert resp.model == "gemini-2.0-flash"
        assert "Mock response" in resp.content
        assert resp.latency_ms == 1.0

    def test_provider_name(self):
        p = MockProvider(ProviderName.OPENAI, "gpt-4o")
        assert p.provider_name == ProviderName.OPENAI

    def test_default_model(self):
        p = MockProvider(ProviderName.XAI, "grok-3")
        assert p.default_model == "grok-3"

    def test_is_available_when_circuit_closed(self):
        p = MockProvider()
        assert p.is_available

    def test_is_unavailable_when_circuit_open(self):
        p = MockProvider()
        p.circuit_breaker.failure_threshold = 1
        with patch("mcp_toolkit.servers.multi_llm.models.time.monotonic", return_value=100.0):
            p.circuit_breaker.record_failure()
        with patch("mcp_toolkit.servers.multi_llm.models.time.monotonic", return_value=110.0):
            assert not p.is_available

    async def test_uses_custom_model_override(self):
        p = MockProvider(ProviderName.GEMINI, "gemini-2.0-flash")
        resp = await p.query("test", model="gemini-2.5-pro-preview-06-05")
        assert resp.model == "gemini-2.5-pro-preview-06-05"

    async def test_content_includes_prompt_prefix(self):
        p = MockProvider(ProviderName.OPENAI, "gpt-4o")
        resp = await p.query("What is Python?")
        assert "openai:gpt-4o" in resp.content


class TestOpenAICompatibleProvider:
    def _make_provider(self, provider: ProviderName = ProviderName.OPENAI) -> OpenAICompatibleProvider:
        return OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            provider=provider,
            default_model="gpt-4o",
        )

    def _mock_response(self, content: str = "Hello!") -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        return mock_resp

    async def test_query_success(self):
        p = self._make_provider()
        mock_resp = self._mock_response("The answer is 42.")
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            resp = await p.query("What is the answer?")
        assert resp.content == "The answer is 42."
        assert resp.provider == ProviderName.OPENAI
        assert resp.input_tokens == 10
        assert resp.output_tokens == 5

    async def test_with_system_prompt_sends_system_message(self):
        p = self._make_provider()
        mock_resp = self._mock_response("Sure!")
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            await p.query("Do X", system_prompt="You are a helpful assistant.")
        call_json = mock_post.call_args.kwargs["json"]
        assert call_json["messages"][0]["role"] == "system"
        assert call_json["messages"][0]["content"] == "You are a helpful assistant."

    async def test_circuit_breaker_records_failure_on_http_error(self):
        p = self._make_provider()
        with patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            side_effect=Exception("Connection refused"),
        ):
            with pytest.raises(Exception):
                await p.query("test")
        assert p.circuit_breaker._failures == 1

    async def test_circuit_breaker_records_success(self):
        p = self._make_provider()
        p.circuit_breaker._failures = 2
        mock_resp = self._mock_response("OK")
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            await p.query("test")
        assert p.circuit_breaker._failures == 0

    async def test_xai_uses_correct_base_url(self):
        p = OpenAICompatibleProvider(
            api_key="xai-key",
            base_url="https://api.x.ai/v1",
            provider=ProviderName.XAI,
            default_model="grok-3",
        )
        mock_resp = self._mock_response("Grok says hi")
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            resp = await p.query("Hello")
        url = mock_post.call_args.args[0]
        assert "api.x.ai" in url
        assert resp.provider == ProviderName.XAI

    async def test_cost_estimated_from_token_counts(self):
        p = self._make_provider()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Hi"}}],
            "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000},
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            resp = await p.query("test", model="gpt-5.4")
        # gpt-5.4: $2.50 input + $15.00 output per 1M = $17.50
        assert abs(resp.cost_usd - 17.50) < 0.01


class TestGeminiProvider:
    def _mock_response(self, content: str = "Gemini response") -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": content}]}}],
            "usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 4},
        }
        return mock_resp

    async def test_query_success(self):
        p = GeminiProvider(api_key="test-key")
        mock_resp = self._mock_response("Gemini says hello!")
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            resp = await p.query("Hello Gemini")
        assert resp.content == "Gemini says hello!"
        assert resp.provider == ProviderName.GEMINI
        assert resp.input_tokens == 8
        assert resp.output_tokens == 4

    async def test_system_prompt_adds_system_instruction(self):
        p = GeminiProvider(api_key="test-key")
        mock_resp = self._mock_response("OK")
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            await p.query("Do X", system_prompt="Be concise.")
        payload = mock_post.call_args.kwargs["json"]
        assert "systemInstruction" in payload
        assert payload["systemInstruction"]["parts"][0]["text"] == "Be concise."

    async def test_no_system_prompt_omits_field(self):
        p = GeminiProvider(api_key="test-key")
        mock_resp = self._mock_response("OK")
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            await p.query("Just a prompt")
        payload = mock_post.call_args.kwargs["json"]
        assert "systemInstruction" not in payload

    async def test_circuit_breaker_records_failure(self):
        p = GeminiProvider(api_key="test-key")
        with patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            side_effect=Exception("timeout"),
        ):
            with pytest.raises(Exception):
                await p.query("test")
        assert p.circuit_breaker._failures == 1

    async def test_uses_key_as_query_param(self):
        p = GeminiProvider(api_key="my-secret-key")
        mock_resp = self._mock_response("OK")
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
            await p.query("test")
        params = mock_post.call_args.kwargs["params"]
        assert params["key"] == "my-secret-key"


# ---------------------------------------------------------------------------
# Wave 1: Protocol + Response Parsing
# ---------------------------------------------------------------------------

class TestLLMProviderProtocol:
    def test_mock_provider_satisfies_protocol(self):
        p = MockProvider(ProviderName.GEMINI, "gemini-2.0-flash")
        assert isinstance(p, LLMProvider)

    def test_openai_provider_satisfies_protocol(self):
        p = OpenAICompatibleProvider(
            api_key="key", base_url="https://api.openai.com/v1",
            provider=ProviderName.OPENAI, default_model="gpt-4o",
        )
        assert isinstance(p, LLMProvider)

    def test_gemini_provider_satisfies_protocol(self):
        p = GeminiProvider(api_key="key")
        assert isinstance(p, LLMProvider)


class TestOpenAIResponseParsing:
    def _make_provider(self) -> OpenAICompatibleProvider:
        return OpenAICompatibleProvider(
            api_key="key", base_url="https://api.openai.com/v1",
            provider=ProviderName.OPENAI, default_model="gpt-4o",
        )

    def _resp(self, data: dict) -> MagicMock:
        m = MagicMock()
        m.raise_for_status = MagicMock()
        m.status_code = 200
        m.json.return_value = data
        return m

    async def test_empty_choices_raises_and_records_failure(self):
        p = self._make_provider()
        mock_resp = self._resp({"choices": [], "usage": {}})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(ValueError, match="Empty choices"):
                await p.query("test")
        assert p.circuit_breaker._failures == 1

    async def test_null_content_raises_and_records_failure(self):
        p = self._make_provider()
        mock_resp = self._resp({"choices": [{"message": {"content": None}}], "usage": {}})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(ValueError, match="Null content"):
                await p.query("test")
        assert p.circuit_breaker._failures == 1

    async def test_missing_message_key_raises_and_records_failure(self):
        p = self._make_provider()
        mock_resp = self._resp({"choices": [{}], "usage": {}})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(KeyError):
                await p.query("test")
        assert p.circuit_breaker._failures == 1

    async def test_missing_usage_defaults_to_zero(self):
        p = self._make_provider()
        mock_resp = self._resp({"choices": [{"message": {"content": "hi"}}]})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            resp = await p.query("test")
        assert resp.input_tokens == 0
        assert resp.output_tokens == 0

    async def test_success_only_recorded_after_successful_parse(self):
        p = self._make_provider()
        p.circuit_breaker._failures = 2
        # Empty choices → failure, not success
        mock_resp = self._resp({"choices": [], "usage": {}})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(ValueError):
                await p.query("test")
        assert p.circuit_breaker._failures == 3


class TestGeminiResponseParsing:
    def _make_provider(self) -> GeminiProvider:
        return GeminiProvider(api_key="key")

    def _resp(self, data: dict) -> MagicMock:
        m = MagicMock()
        m.raise_for_status = MagicMock()
        m.status_code = 200
        m.json.return_value = data
        return m

    async def test_empty_candidates_raises_and_records_failure(self):
        p = self._make_provider()
        mock_resp = self._resp({"candidates": []})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(ValueError, match="No candidates"):
                await p.query("test")
        assert p.circuit_breaker._failures == 1

    async def test_no_candidates_key_raises_and_records_failure(self):
        p = self._make_provider()
        mock_resp = self._resp({})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(ValueError, match="No candidates"):
                await p.query("test")
        assert p.circuit_breaker._failures == 1

    async def test_missing_parts_raises_and_records_failure(self):
        p = self._make_provider()
        mock_resp = self._resp({"candidates": [{"content": {}}]})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(KeyError):
                await p.query("test")
        assert p.circuit_breaker._failures == 1

    async def test_missing_usage_defaults_to_zero(self):
        p = self._make_provider()
        mock_resp = self._resp({
            "candidates": [{"content": {"parts": [{"text": "hi"}]}}]
        })
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            resp = await p.query("test")
        assert resp.input_tokens == 0
        assert resp.output_tokens == 0

    async def test_success_only_recorded_after_successful_parse(self):
        p = self._make_provider()
        p.circuit_breaker._failures = 2
        mock_resp = self._resp({"candidates": []})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(ValueError):
                await p.query("test")
        assert p.circuit_breaker._failures == 3


# ---------------------------------------------------------------------------
# Wave 2: Connection Pooling + Retry
# ---------------------------------------------------------------------------

class TestConnectionPooling:
    def test_openai_client_created_in_init(self):
        p = OpenAICompatibleProvider(
            api_key="key", base_url="https://api.openai.com/v1",
            provider=ProviderName.OPENAI, default_model="gpt-4o",
        )
        assert isinstance(p._client, httpx.AsyncClient)

    async def test_client_reused_across_calls(self):
        p = OpenAICompatibleProvider(
            api_key="key", base_url="https://api.openai.com/v1",
            provider=ProviderName.OPENAI, default_model="gpt-4o",
        )
        client_before = p._client
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            await p.query("first")
            await p.query("second")
        assert p._client is client_before


class TestRetryLogic:
    def _openai_provider(self) -> OpenAICompatibleProvider:
        return OpenAICompatibleProvider(
            api_key="key", base_url="https://api.openai.com/v1",
            provider=ProviderName.OPENAI, default_model="gpt-4o",
        )

    def _ok_resp(self, content: str = "ok") -> MagicMock:
        m = MagicMock()
        m.status_code = 200
        m.raise_for_status = MagicMock()
        m.json.return_value = {
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
        return m

    def _status_resp(self, status: int) -> MagicMock:
        m = MagicMock()
        m.status_code = status
        m.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                f"{status}", request=MagicMock(), response=MagicMock()
            )
        )
        return m

    async def test_429_retries_then_succeeds(self):
        p = self._openai_provider()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=[self._status_resp(429), self._ok_resp()])
        p._client = mock_client
        with patch("mcp_toolkit.servers.multi_llm.providers.asyncio.sleep", new_callable=AsyncMock):
            resp = await p.query("test")
        assert resp.content == "ok"
        assert mock_client.post.call_count == 2

    async def test_503_retries_then_succeeds(self):
        p = self._openai_provider()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=[self._status_resp(503), self._ok_resp()])
        p._client = mock_client
        with patch("mcp_toolkit.servers.multi_llm.providers.asyncio.sleep", new_callable=AsyncMock):
            resp = await p.query("test")
        assert resp.content == "ok"
        assert mock_client.post.call_count == 2

    async def test_401_no_retry(self):
        p = self._openai_provider()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=self._status_resp(401))
        p._client = mock_client
        with pytest.raises(httpx.HTTPStatusError):
            await p.query("test")
        assert mock_client.post.call_count == 1

    async def test_429_both_fail_records_circuit_failure(self):
        p = self._openai_provider()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=self._status_resp(429))
        p._client = mock_client
        with patch("mcp_toolkit.servers.multi_llm.providers.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(httpx.HTTPStatusError):
                await p.query("test")
        assert mock_client.post.call_count == 2
        assert p.circuit_breaker._failures == 1


# ---------------------------------------------------------------------------
# Wave 3: Router + Main
# ---------------------------------------------------------------------------

class TestRouter:
    def test_cheap_priority_first_is_gemini_flash_lite(self):
        from mcp_toolkit.servers.multi_llm.router import CHEAP_PRIORITY
        assert CHEAP_PRIORITY[0] == (ProviderName.GEMINI, "gemini-3.1-flash-lite-preview")

    def test_best_priority_first_is_openai_gpt54(self):
        from mcp_toolkit.servers.multi_llm.router import BEST_PRIORITY
        assert BEST_PRIORITY[0] == (ProviderName.OPENAI, "gpt-5.4")

    def test_all_router_models_in_pricing(self):
        from mcp_toolkit.servers.multi_llm.router import BEST_PRIORITY, CHEAP_PRIORITY
        from mcp_toolkit.servers.multi_llm.pricing import PRICING
        for _, model in CHEAP_PRIORITY + BEST_PRIORITY:
            assert model in PRICING, f"Model {model!r} missing from PRICING"


class TestMain:
    def test_no_env_vars_configures_empty_providers(self):
        from mcp_toolkit.servers.multi_llm import server as llm_server
        with patch("mcp_toolkit.servers.multi_llm.server.configure") as mock_configure:
            with patch.object(llm_server.mcp, "run"):
                with patch.dict(
                    os.environ,
                    {"GEMINI_API_KEY": "", "OPENAI_API_KEY": "", "XAI_API_KEY": ""},
                ):
                    llm_server.main()
        providers = mock_configure.call_args.kwargs["providers"]
        assert len(providers) == 0

    def test_gemini_only_env_var_configures_only_gemini(self):
        from mcp_toolkit.servers.multi_llm import server as llm_server
        with patch("mcp_toolkit.servers.multi_llm.server.configure") as mock_configure:
            with patch.object(llm_server.mcp, "run"):
                with patch.dict(
                    os.environ,
                    {
                        "GEMINI_API_KEY": "test-gemini-key",
                        "OPENAI_API_KEY": "",
                        "XAI_API_KEY": "",
                    },
                ):
                    llm_server.main()
        providers = mock_configure.call_args.kwargs["providers"]
        assert ProviderName.GEMINI in providers
        assert ProviderName.OPENAI not in providers
        assert ProviderName.XAI not in providers
