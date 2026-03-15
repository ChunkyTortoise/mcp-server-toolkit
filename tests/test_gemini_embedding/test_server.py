"""Tests for Gemini Embedding MCP server tools."""

from __future__ import annotations

import pytest

from mcp_toolkit.framework.testing import MCPTestClient
from mcp_toolkit.servers.gemini_embedding.server import MockEmbeddingClient, configure
from mcp_toolkit.servers.gemini_embedding.server import mcp as embedding_mcp
from mcp_toolkit.servers.gemini_embedding.vector_store import InMemoryVectorStore


@pytest.fixture
def client():
    configure(client=MockEmbeddingClient(), store=InMemoryVectorStore(), default_dimensions=64)
    return MCPTestClient(embedding_mcp)


class TestEmbedText:
    async def test_embed_returns_summary(self, client):
        result = await client.call_tool("embed_text", {"text": "hello world"})
        assert "64-dim vector" in result
        assert "Preview (first 5)" in result

    async def test_embed_shows_char_count(self, client):
        text = "Python is great"
        result = await client.call_tool("embed_text", {"text": text})
        assert str(len(text)) in result

    async def test_embed_custom_task_type(self, client):
        result = await client.call_tool(
            "embed_text", {"text": "hello", "task_type": "RETRIEVAL_DOCUMENT"}
        )
        assert "RETRIEVAL_DOCUMENT" in result

    async def test_embed_custom_dimensions(self, client):
        result = await client.call_tool("embed_text", {"text": "hi", "dimensions": 128})
        assert "128-dim vector" in result


class TestIndexText:
    async def test_index_returns_confirmation(self, client):
        result = await client.call_tool(
            "index_text", {"text": "test document", "item_id": "doc1"}
        )
        assert "Indexed 'doc1'" in result
        assert "Total items: 1" in result

    async def test_index_invalid_metadata(self, client):
        result = await client.call_tool(
            "index_text", {"text": "doc", "item_id": "x", "metadata": "not json"}
        )
        assert "Error" in result

    async def test_index_with_metadata(self, client):
        result = await client.call_tool(
            "index_text",
            {"text": "doc", "item_id": "y", "metadata": '{"source": "readme"}'},
        )
        assert "Indexed" in result

    async def test_index_multiple_increments_count(self, client):
        await client.call_tool("index_text", {"text": "one", "item_id": "a"})
        result = await client.call_tool("index_text", {"text": "two", "item_id": "b"})
        assert "Total items: 2" in result


class TestSearch:
    async def test_search_empty_index(self, client):
        result = await client.call_tool("search", {"query": "anything"})
        assert "empty" in result.lower()

    async def test_search_finds_indexed_item(self, client):
        await client.call_tool("index_text", {"text": "Python async patterns", "item_id": "p1"})
        result = await client.call_tool("search", {"query": "Python async"})
        assert "p1" in result

    async def test_search_returns_scores(self, client):
        await client.call_tool("index_text", {"text": "machine learning", "item_id": "ml"})
        result = await client.call_tool("search", {"query": "machine learning"})
        assert "score=" in result

    async def test_search_top_k_limits_results(self, client):
        for i in range(5):
            await client.call_tool("index_text", {"text": f"doc {i}", "item_id": f"d{i}"})
        result = await client.call_tool("search", {"query": "doc", "top_k": 2})
        assert "Top 2 results" in result


class TestSimilarity:
    async def test_similarity_returns_score(self, client):
        result = await client.call_tool(
            "similarity", {"text_a": "Python code", "text_b": "JavaScript code"}
        )
        assert "Similarity score:" in result

    async def test_identical_texts_high_score(self, client):
        result = await client.call_tool(
            "similarity", {"text_a": "hello world", "text_b": "hello world"}
        )
        assert "1.0000" in result

    async def test_similarity_shows_label(self, client):
        result = await client.call_tool(
            "similarity", {"text_a": "async programming", "text_b": "sync blocking IO"}
        )
        # Should contain one of the label strings
        labels = {"very similar", "similar", "somewhat related", "dissimilar"}
        assert any(label in result for label in labels)


class TestListIndexed:
    async def test_list_empty_index(self, client):
        result = await client.call_tool("list_indexed", {})
        assert "empty" in result.lower()

    async def test_list_shows_item_ids(self, client):
        await client.call_tool("index_text", {"text": "some text", "item_id": "my_doc"})
        result = await client.call_tool("list_indexed", {})
        assert "my_doc" in result

    async def test_list_shows_count(self, client):
        await client.call_tool("index_text", {"text": "a", "item_id": "a1"})
        await client.call_tool("index_text", {"text": "b", "item_id": "b1"})
        result = await client.call_tool("list_indexed", {})
        assert "2 indexed items" in result


class TestClearIndex:
    async def test_clear_empty_index(self, client):
        result = await client.call_tool("clear_index", {})
        assert "0 item" in result

    async def test_clear_removes_items(self, client):
        await client.call_tool("index_text", {"text": "x", "item_id": "x1"})
        await client.call_tool("index_text", {"text": "y", "item_id": "y1"})
        result = await client.call_tool("clear_index", {})
        assert "2" in result
        # Verify it's actually cleared
        list_result = await client.call_tool("list_indexed", {})
        assert "empty" in list_result.lower()


class TestEmbeddingClientAwait:
    """Regression test: GeminiEmbeddingClient.embed must use `await client.post(...)`."""

    async def test_embed_is_coroutine(self):
        """Verify embed() is a proper async function that returns a list, not a coroutine."""
        from mcp_toolkit.servers.gemini_embedding.embedding_client import GeminiEmbeddingClient
        from unittest.mock import AsyncMock, patch, MagicMock
        import httpx

        client = GeminiEmbeddingClient(api_key="test-key")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"embedding": {"values": [0.1, 0.2, 0.3]}}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            result = await client.embed("hello", task_type="SEMANTIC_SIMILARITY", dimensions=3)

        assert isinstance(result, list)
        assert result == [0.1, 0.2, 0.3]


class TestToolListing:
    async def test_has_expected_tools(self, client):
        tools = await client.list_tools()
        names = {t["name"] for t in tools}
        assert "embed_text" in names
        assert "index_text" in names
        assert "search" in names
        assert "similarity" in names
        assert "list_indexed" in names
        assert "clear_index" in names
