"""LLM provider implementations: Gemini REST, OpenAI-compatible REST, and Mock."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Protocol, runtime_checkable

import httpx

from mcp_toolkit.servers.multi_llm.models import CircuitBreaker, LLMResponse, ProviderName
from mcp_toolkit.servers.multi_llm.pricing import estimate_cost


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM provider implementations."""

    circuit_breaker: CircuitBreaker

    @property
    def provider_name(self) -> ProviderName: ...

    @property
    def default_model(self) -> str: ...

    @property
    def is_available(self) -> bool: ...

    async def query(
        self,
        prompt: str,
        model: str = "",
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse: ...


async def _post_with_retry(
    client: httpx.AsyncClient, url: str, **kwargs: Any
) -> httpx.Response:
    """POST with a single retry on 429 (rate limit) or 503 (service unavailable)."""
    resp = await client.post(url, **kwargs)
    if resp.status_code in (429, 503):
        await asyncio.sleep(1.0)
        resp = await client.post(url, **kwargs)
    resp.raise_for_status()
    return resp


class MockProvider:
    """Deterministic provider for testing — never makes real HTTP calls."""

    def __init__(
        self,
        provider: ProviderName = ProviderName.GEMINI,
        model: str = "gemini-2.0-flash",
    ) -> None:
        self._provider = provider
        self._model = model
        self.circuit_breaker = CircuitBreaker()

    @property
    def provider_name(self) -> ProviderName:
        return self._provider

    @property
    def default_model(self) -> str:
        return self._model

    @property
    def is_available(self) -> bool:
        return not self.circuit_breaker.is_open()

    async def query(
        self,
        prompt: str,
        model: str = "",
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        m = model or self._model
        content = f"[{self._provider.value}:{m}] Mock response to: {prompt[:50]}"
        input_tokens = len(prompt.split())
        output_tokens = len(content.split())
        return LLMResponse(
            provider=self._provider,
            model=m,
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=estimate_cost(m, input_tokens, output_tokens),
            latency_ms=1.0,
        )


class OpenAICompatibleProvider:
    """Provider for OpenAI-compatible REST APIs.

    Used for both OpenAI (base_url=https://api.openai.com/v1) and
    xAI/Grok (base_url=https://api.x.ai/v1) which share the same API shape.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        provider: ProviderName,
        default_model: str,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._provider = provider
        self._default_model = default_model
        self.circuit_breaker = CircuitBreaker()
        self._client = httpx.AsyncClient(timeout=30.0)

    @property
    def provider_name(self) -> ProviderName:
        return self._provider

    @property
    def default_model(self) -> str:
        return self._default_model

    @property
    def is_available(self) -> bool:
        return not self.circuit_breaker.is_open()

    async def query(
        self,
        prompt: str,
        model: str = "",
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        m = model or self._default_model
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        start = time.monotonic()
        try:
            resp = await _post_with_retry(
                self._client,
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": m,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            data = resp.json()
            choices = data.get("choices") or []
            if not choices:
                raise ValueError("Empty choices in OpenAI response")
            content = choices[0]["message"]["content"]
            if content is None:
                raise ValueError("Null content in OpenAI response")
            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
        except Exception:
            self.circuit_breaker.record_failure()
            raise

        latency_ms = (time.monotonic() - start) * 1000
        self.circuit_breaker.record_success()

        return LLMResponse(
            provider=self._provider,
            model=m,
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=estimate_cost(m, input_tokens, output_tokens),
            latency_ms=latency_ms,
        )


class GeminiProvider:
    """Provider for Google Gemini REST API."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, api_key: str, default_model: str = "gemini-2.0-flash") -> None:
        self._api_key = api_key
        self._default_model = default_model
        self.circuit_breaker = CircuitBreaker()
        self._client = httpx.AsyncClient(timeout=30.0)

    @property
    def provider_name(self) -> ProviderName:
        return ProviderName.GEMINI

    @property
    def default_model(self) -> str:
        return self._default_model

    @property
    def is_available(self) -> bool:
        return not self.circuit_breaker.is_open()

    async def query(
        self,
        prompt: str,
        model: str = "",
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        m = model or self._default_model
        payload: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}], "role": "user"}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        start = time.monotonic()
        try:
            resp = await _post_with_retry(
                self._client,
                f"{self.BASE_URL}/models/{m}:generateContent",
                params={"key": self._api_key},
                json=payload,
            )
            data = resp.json()
            candidates = data.get("candidates") or []
            if not candidates:
                raise ValueError("No candidates in Gemini response (safety filter or empty)")
            content = candidates[0]["content"]["parts"][0]["text"]
            usage = data.get("usageMetadata", {})
            input_tokens = usage.get("promptTokenCount", 0)
            output_tokens = usage.get("candidatesTokenCount", 0)
        except Exception:
            self.circuit_breaker.record_failure()
            raise

        latency_ms = (time.monotonic() - start) * 1000
        self.circuit_breaker.record_success()

        return LLMResponse(
            provider=ProviderName.GEMINI,
            model=m,
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=estimate_cost(m, input_tokens, output_tokens),
            latency_ms=latency_ms,
        )
