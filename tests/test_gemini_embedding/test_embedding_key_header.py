"""Embedding client sends the API key in a header, not the URL."""

from __future__ import annotations

from unittest.mock import patch

import httpx

from mcp_toolkit.servers.gemini_embedding.embedding_client import GeminiEmbeddingClient


def _client_factory(transport: httpx.MockTransport):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    return factory


def _capture(body: dict):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=body)

    return seen, httpx.MockTransport(handler)


async def test_embed_sends_key_header():
    secret = "embed-secret"
    seen, transport = _capture({"embedding": {"values": [0.1, 0.2]}})
    with patch(
        "mcp_toolkit.servers.gemini_embedding.embedding_client.httpx.AsyncClient",
        side_effect=_client_factory(transport),
    ):
        client = GeminiEmbeddingClient(api_key=secret)
        values = await client.embed("hello")
    assert values == [0.1, 0.2]
    request = seen[0]
    assert secret not in str(request.url)
    assert "key=" not in str(request.url)
    assert request.headers.get("x-goog-api-key") == secret


async def test_embed_batch_sends_key_header():
    secret = "batch-secret"
    seen, transport = _capture({"embeddings": [{"values": [0.3]}, {"values": [0.4]}]})
    with patch(
        "mcp_toolkit.servers.gemini_embedding.embedding_client.httpx.AsyncClient",
        side_effect=_client_factory(transport),
    ):
        client = GeminiEmbeddingClient(api_key=secret)
        values = await client.embed_batch(["a", "b"])
    assert values == [[0.3], [0.4]]
    request = seen[0]
    assert secret not in str(request.url)
    assert "key=" not in str(request.url)
    assert request.headers.get("x-goog-api-key") == secret
