"""Agentic RAG pipeline — dual-mode embed/retrieve/synthesize with EnhancedMCP tools."""

from __future__ import annotations

import hashlib
import os
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from mcp_toolkit import EnhancedMCP

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Chunk:
    id: str
    text: str
    source: str
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


DEMO_CHUNKS: list[Chunk] = [
    Chunk(
        "c1",
        "Retrieval-Augmented Generation (RAG) combines a retrieval step with a generative model to produce grounded, cited answers.",
        "RAG paper (Lewis et al., 2020)",
        0.95,
    ),
    Chunk(
        "c2",
        "The retrieval step typically uses dense embeddings (e.g., text-embedding-004) stored in a vector database such as pgvector or Pinecone.",
        "Embedding guide",
        0.90,
    ),
    Chunk(
        "c3",
        "Agentic RAG adds tool-use loops: the agent decides what to retrieve, when to stop, and how to combine sources — rather than doing a single retrieval pass.",
        "Agentic patterns (2024)",
        0.88,
    ),
    Chunk(
        "c4",
        "pgvector is a PostgreSQL extension that stores and queries dense vectors with HNSW or IVFFlat indexes.",
        "pgvector docs",
        0.82,
    ),
    Chunk(
        "c5",
        "Faithfulness is measured by whether the answer is entailed by the retrieved context; recall measures whether relevant chunks were retrieved at all.",
        "RAGAS paper",
        0.78,
    ),
]


# ---------------------------------------------------------------------------
# Mode detection + rate limiting
# ---------------------------------------------------------------------------


def detect_mode() -> Literal["demo", "live"]:
    """Return live when ANTHROPIC_API_KEY is set; otherwise demo."""
    return "live" if os.environ.get("ANTHROPIC_API_KEY") else "demo"


def retrieval_backend_label() -> str:
    """Human-readable retrieval backend label."""
    return "pgvector" if os.environ.get("PGVECTOR_URL") else "demo (in-memory)"


class RateLimiter:
    """Sliding-window rate limiter keyed by caller identifier."""

    def __init__(self, max_calls: int, window_seconds: float) -> None:
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._calls: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        window_start = now - self.window_seconds
        recent = [t for t in self._calls[key] if t > window_start]
        if len(recent) >= self.max_calls:
            self._calls[key] = recent
            return False
        recent.append(now)
        self._calls[key] = recent
        return True


# ---------------------------------------------------------------------------
# Pipeline components
# ---------------------------------------------------------------------------


async def embed_query(query: str) -> list[float]:
    """Embed query. Deterministic fake embedding for demo (128-dim)."""
    h = int(hashlib.sha256(query.encode()).hexdigest(), 16)
    return [(h >> i & 0xFF) / 255.0 for i in range(128)]


async def retrieve_chunks(query_embedding: list[float], top_k: int = 4) -> list[Chunk]:
    """Retrieve relevant chunks. Falls back to demo data if no PGVECTOR_URL."""
    pgvector_url = os.environ.get("PGVECTOR_URL", "")
    if not pgvector_url:
        return sorted(DEMO_CHUNKS, key=lambda c: c.score, reverse=True)[:top_k]

    try:
        import asyncpg  # type: ignore[import-untyped]

        conn = await asyncpg.connect(pgvector_url)
        rows = await conn.fetch(
            "SELECT id, text, source, 1 - (embedding <=> $1::vector) AS score "
            "FROM documents ORDER BY score DESC LIMIT $2",
            query_embedding,
            top_k,
        )
        await conn.close()
        return [Chunk(r["id"], r["text"], r["source"], float(r["score"])) for r in rows]
    except Exception:
        return DEMO_CHUNKS[:top_k]


async def _demo_synthesize(query: str, chunks: list[Chunk]) -> str:
    """Template answer for demo mode — no API keys required."""
    citations = " ".join(f"[{i + 1}]" for i in range(len(chunks)))
    preview = chunks[0].text[:120] if chunks else "No sources retrieved."
    return (
        f"Based on the retrieved sources {citations}: {preview}... "
        f"(Demo mode — set ANTHROPIC_API_KEY for live synthesis.)"
    )


async def synthesize(query: str, chunks: list[Chunk]) -> str:
    """Synthesize a cited answer. Uses Anthropic when key available."""
    context = "\n\n".join(
        f"[{i + 1}] ({c.source})\n{c.text}" for i, c in enumerate(chunks)
    )
    prompt = (
        f"Answer this question using ONLY the sources below. "
        f"Cite each source as [N].\n\n"
        f"Question: {query}\n\n"
        f"Sources:\n{context}\n\n"
        f"Answer:"
    )

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text
        except Exception as exc:
            demo_answer = await _demo_synthesize(query, chunks)
            return (
                f"{demo_answer}\n\n"
                f"(Anthropic synthesis failed — falling back to demo mode: {exc})"
            )

    return await _demo_synthesize(query, chunks)


async def run_pipeline(query: str, top_k: int = 4) -> tuple[str, list[Chunk], float]:
    """Full RAG pipeline. Returns (answer, chunks, elapsed_seconds)."""
    t0 = time.monotonic()
    embedding = await embed_query(query)
    chunks = await retrieve_chunks(embedding, top_k=top_k)
    answer = await synthesize(query, chunks)
    elapsed = time.monotonic() - t0
    return answer, chunks, elapsed


# ---------------------------------------------------------------------------
# EnhancedMCP tool registration
# ---------------------------------------------------------------------------

mcp = EnhancedMCP("agentic-rag-demo")


@mcp.tool()
async def embed_query_tool(query: str) -> list[float]:
    """Embed a search query into a dense vector."""
    return await embed_query(query)


@mcp.tool()
async def retrieve_chunks_tool(query_embedding: list[float], top_k: int = 4) -> list[dict[str, Any]]:
    """Retrieve relevant document chunks for a query embedding."""
    chunks = await retrieve_chunks(query_embedding, top_k=top_k)
    return [asdict(c) for c in chunks]


@mcp.tool()
async def synthesize_tool(query: str, chunks: list[dict[str, Any]]) -> str:
    """Synthesize a cited answer from retrieved chunks."""
    chunk_objs = [
        Chunk(
            id=c["id"],
            text=c["text"],
            source=c["source"],
            score=float(c.get("score", 0.0)),
            metadata=c.get("metadata", {}),
        )
        for c in chunks
    ]
    return await synthesize(query, chunk_objs)
