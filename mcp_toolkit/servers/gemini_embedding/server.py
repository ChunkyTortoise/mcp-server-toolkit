"""Gemini Embedding 2 MCP Server — Semantic search and vector indexing."""

from __future__ import annotations

import hashlib
import json
import os
import struct
from typing import Protocol

from mcp_toolkit.framework.base_server import EnhancedMCP
from mcp_toolkit.servers.gemini_embedding.embedding_client import GeminiEmbeddingClient
from mcp_toolkit.servers.gemini_embedding.vector_store import IndexedItem, InMemoryVectorStore

mcp = EnhancedMCP("gemini-embedding")

_DEFAULT_DIMENSIONS = 768


class EmbeddingClient(Protocol):
    async def embed(self, text: str, task_type: str, dimensions: int) -> list[float]: ...

    async def embed_batch(
        self, texts: list[str], task_type: str, dimensions: int
    ) -> list[list[float]]: ...


class MockEmbeddingClient:
    """Deterministic embedding client for testing — SHA-256 hash-based vectors."""

    def _hash_vector(self, text: str, dimensions: int) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        # Unpack as many floats as possible from the digest, then cycle
        raw = list(struct.unpack("8f", digest[:32]))
        vector: list[float] = []
        while len(vector) < dimensions:
            vector.extend(raw)
        return vector[:dimensions]

    async def embed(self, text: str, task_type: str, dimensions: int) -> list[float]:
        return self._hash_vector(text, dimensions)

    async def embed_batch(
        self, texts: list[str], task_type: str, dimensions: int
    ) -> list[list[float]]:
        return [self._hash_vector(t, dimensions) for t in texts]


_client: EmbeddingClient = MockEmbeddingClient()
_store: InMemoryVectorStore = InMemoryVectorStore()
_default_dimensions: int = _DEFAULT_DIMENSIONS


def configure(
    client: EmbeddingClient | None = None,
    store: InMemoryVectorStore | None = None,
    default_dimensions: int | None = None,
) -> None:
    global _client, _store, _default_dimensions
    if client is not None:
        _client = client
    if store is not None:
        _store = store
    if default_dimensions is not None:
        _default_dimensions = default_dimensions


@mcp.tool()
async def embed_text(
    text: str,
    task_type: str = "SEMANTIC_SIMILARITY",
    dimensions: int = 0,
) -> str:
    """Embed text using Gemini Embedding 2 and return a vector summary.

    Args:
        text: The text to embed.
        task_type: Embedding task type (SEMANTIC_SIMILARITY, RETRIEVAL_DOCUMENT,
                   RETRIEVAL_QUERY, CLASSIFICATION, CLUSTERING).
        dimensions: Output dimensions (0 = use server default).
    """
    dims = dimensions if dimensions > 0 else _default_dimensions
    vector = await _client.embed(text=text, task_type=task_type, dimensions=dims)
    preview = ", ".join(f"{v:.4f}" for v in vector[:5])
    return (
        f"Embedded {len(text)} chars → {dims}-dim vector\n"
        f"Task type: {task_type}\n"
        f"Preview (first 5): [{preview}, ...]"
    )


@mcp.tool()
async def index_text(
    text: str,
    item_id: str,
    metadata: str = "{}",
) -> str:
    """Index text for later semantic search.

    Args:
        text: The text to index.
        item_id: Unique identifier for this item.
        metadata: JSON string of arbitrary metadata (e.g., '{"source": "readme"}').
    """
    try:
        meta_dict = json.loads(metadata)
    except json.JSONDecodeError:
        return "Error: Invalid JSON in metadata."

    vector = await _client.embed(
        text=text, task_type="RETRIEVAL_DOCUMENT", dimensions=_default_dimensions
    )
    item = IndexedItem(id=item_id, text=text, vector=vector, metadata=meta_dict)
    _store.add(item)
    return f"Indexed '{item_id}' ({len(text)} chars). Total items: {_store.count}"


@mcp.tool()
async def search(
    query: str,
    top_k: int = 5,
) -> str:
    """Semantic search across the vector index.

    Args:
        query: The search query.
        top_k: Number of results to return (default 5).
    """
    if _store.count == 0:
        return "Index is empty. Use index_text to add items first."

    query_vector = await _client.embed(
        text=query, task_type="RETRIEVAL_QUERY", dimensions=_default_dimensions
    )
    results = _store.search(query_vector=query_vector, top_k=top_k)

    if not results:
        return "No results found."

    lines = [f"**Top {len(results)} results for:** {query!r}\n"]
    for i, (item, score) in enumerate(results, 1):
        preview = item.text[:80].replace("\n", " ")
        if len(item.text) > 80:
            preview += "..."
        lines.append(f"{i}. [{item.id}] score={score:.4f}\n   {preview}")
    return "\n".join(lines)


@mcp.tool()
async def similarity(
    text_a: str,
    text_b: str,
) -> str:
    """Compute cosine similarity between two texts.

    Args:
        text_a: First text.
        text_b: Second text.
    """
    from mcp_toolkit.servers.gemini_embedding.vector_store import cosine_similarity

    vectors = await _client.embed_batch(
        texts=[text_a, text_b],
        task_type="SEMANTIC_SIMILARITY",
        dimensions=_default_dimensions,
    )
    score = cosine_similarity(vectors[0], vectors[1])
    label = (
        "very similar" if score > 0.9
        else "similar" if score > 0.7
        else "somewhat related" if score > 0.4
        else "dissimilar"
    )
    return f"Similarity score: {score:.4f} ({label})\n\nText A: {text_a[:60]!r}\nText B: {text_b[:60]!r}"


@mcp.tool()
async def list_indexed() -> str:
    """List all items in the vector index."""
    items = _store.list_items()
    if not items:
        return "Index is empty."

    lines = [f"**{_store.count} indexed items:**\n"]
    for item in items:
        preview = item.text[:60].replace("\n", " ")
        if len(item.text) > 60:
            preview += "..."
        meta_str = f" {item.metadata}" if item.metadata else ""
        lines.append(f"- [{item.id}]{meta_str}: {preview!r}")
    return "\n".join(lines)


@mcp.tool()
async def clear_index() -> str:
    """Clear all items from the vector index."""
    count = _store.count
    _store.clear()
    return f"Index cleared. Removed {count} item(s)."


def main() -> None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        configure(client=GeminiEmbeddingClient(api_key=api_key))
    mcp.run()


if __name__ == "__main__":
    main()
