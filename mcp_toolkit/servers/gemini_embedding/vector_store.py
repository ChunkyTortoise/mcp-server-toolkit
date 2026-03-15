"""In-memory vector store for semantic search."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


@dataclass
class IndexedItem:
    id: str
    text: str
    vector: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)
    indexed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class InMemoryVectorStore:
    """Thread-unsafe in-memory vector store for MCP sessions."""

    def __init__(self) -> None:
        self._items: dict[str, IndexedItem] = {}

    def add(self, item: IndexedItem) -> None:
        self._items[item.id] = item

    def search(self, query_vector: list[float], top_k: int = 5) -> list[tuple[IndexedItem, float]]:
        """Return top_k items sorted by cosine similarity descending."""
        scored = [
            (item, cosine_similarity(query_vector, item.vector))
            for item in self._items.values()
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def get(self, item_id: str) -> IndexedItem | None:
        return self._items.get(item_id)

    def remove(self, item_id: str) -> bool:
        if item_id in self._items:
            del self._items[item_id]
            return True
        return False

    def list_items(self) -> list[IndexedItem]:
        return list(self._items.values())

    def clear(self) -> None:
        self._items.clear()

    @property
    def count(self) -> int:
        return len(self._items)
