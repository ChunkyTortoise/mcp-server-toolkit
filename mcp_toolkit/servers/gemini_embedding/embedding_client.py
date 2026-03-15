"""Gemini Embedding 2 API client."""

from __future__ import annotations

import httpx

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_MODEL = "gemini-embedding-2-preview"


class GeminiEmbeddingClient:
    """HTTP client for Gemini Embedding 2 API."""

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    async def embed(
        self,
        text: str,
        task_type: str = "SEMANTIC_SIMILARITY",
        dimensions: int = 768,
    ) -> list[float]:
        """Embed a single text string."""
        url = f"{_BASE_URL}/{_MODEL}:embedContent?key={self._api_key}"
        payload = {
            "model": f"models/{_MODEL}",
            "content": {"parts": [{"text": text}]},
            "taskType": task_type,
            "outputDimensionality": dimensions,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        return data["embedding"]["values"]

    async def embed_batch(
        self,
        texts: list[str],
        task_type: str = "SEMANTIC_SIMILARITY",
        dimensions: int = 768,
    ) -> list[list[float]]:
        """Embed multiple texts in a single request."""
        url = f"{_BASE_URL}/{_MODEL}:batchEmbedContents?key={self._api_key}"
        requests = [
            {
                "model": f"models/{_MODEL}",
                "content": {"parts": [{"text": t}]},
                "taskType": task_type,
                "outputDimensionality": dimensions,
            }
            for t in texts
        ]
        payload = {"requests": requests}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        return [item["values"] for item in data["embeddings"]]
