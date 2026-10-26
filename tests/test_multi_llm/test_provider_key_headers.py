"""Gemini provider sends the API key in a header, not the URL."""

from __future__ import annotations

from unittest.mock import patch

import httpx

from mcp_toolkit.servers.multi_llm.providers import GeminiProvider


def _client_factory(transport: httpx.MockTransport):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    return factory


async def test_gemini_key_is_header_not_url():
    secret = "my-secret-key"
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
            },
        )

    transport = httpx.MockTransport(handler)
    with patch(
        "mcp_toolkit.servers.multi_llm.providers.httpx.AsyncClient",
        side_effect=_client_factory(transport),
    ):
        provider = GeminiProvider(api_key=secret)
        try:
            await provider.query("hello")
        finally:
            await provider._client.aclose()

    assert seen
    request = seen[0]
    assert secret not in str(request.url)
    assert "key=" not in str(request.url)
    assert request.headers.get("x-goog-api-key") == secret
