"""Unit tests for InMemoryVectorStore and cosine_similarity."""

from __future__ import annotations

import math

import pytest

from mcp_toolkit.servers.gemini_embedding.vector_store import (
    IndexedItem,
    InMemoryVectorStore,
    cosine_similarity,
)


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 0.0, 0.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_zero_vector_returns_zero(self):
        a = [0.0, 0.0]
        b = [1.0, 0.0]
        assert cosine_similarity(a, b) == 0.0

    def test_similar_vectors(self):
        a = [1.0, 1.0]
        b = [1.0, 0.9]
        score = cosine_similarity(a, b)
        assert score > 0.99


class TestInMemoryVectorStore:
    def _item(self, id: str, vector: list[float], text: str = "test") -> IndexedItem:
        return IndexedItem(id=id, text=text, vector=vector)

    def test_add_and_count(self):
        store = InMemoryVectorStore()
        store.add(self._item("a", [1.0, 0.0]))
        assert store.count == 1

    def test_get_existing(self):
        store = InMemoryVectorStore()
        item = self._item("x", [0.5, 0.5], text="hello")
        store.add(item)
        result = store.get("x")
        assert result is not None
        assert result.text == "hello"

    def test_get_missing_returns_none(self):
        store = InMemoryVectorStore()
        assert store.get("nonexistent") is None

    def test_remove_existing(self):
        store = InMemoryVectorStore()
        store.add(self._item("r", [1.0, 0.0]))
        assert store.remove("r") is True
        assert store.count == 0

    def test_remove_missing_returns_false(self):
        store = InMemoryVectorStore()
        assert store.remove("ghost") is False

    def test_search_returns_top_k(self):
        store = InMemoryVectorStore()
        store.add(self._item("a", [1.0, 0.0]))
        store.add(self._item("b", [0.0, 1.0]))
        store.add(self._item("c", [0.7, 0.7]))
        results = store.search([1.0, 0.0], top_k=2)
        assert len(results) == 2
        assert results[0][0].id == "a"

    def test_search_sorted_by_score(self):
        store = InMemoryVectorStore()
        store.add(self._item("near", [0.99, 0.01]))
        store.add(self._item("far", [0.01, 0.99]))
        results = store.search([1.0, 0.0], top_k=5)
        scores = [s for _, s in results]
        assert scores == sorted(scores, reverse=True)

    def test_list_items(self):
        store = InMemoryVectorStore()
        store.add(self._item("a", [1.0]))
        store.add(self._item("b", [0.0]))
        assert len(store.list_items()) == 2

    def test_clear_resets_count(self):
        store = InMemoryVectorStore()
        store.add(self._item("a", [1.0]))
        store.clear()
        assert store.count == 0

    def test_overwrite_same_id(self):
        store = InMemoryVectorStore()
        store.add(self._item("dup", [1.0, 0.0], "first"))
        store.add(self._item("dup", [0.0, 1.0], "second"))
        assert store.count == 1
        assert store.get("dup").text == "second"
