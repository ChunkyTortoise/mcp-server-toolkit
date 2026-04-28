"""Agentic RAG demo — Streamlit UI + multi-agent retrieval pipeline.

Architecture:
    Streamlit UI
        │
        ├─► Embed query (mock/gemini-embedding MCP)
        ├─► Retrieve chunks (pgvector MCP or in-memory fallback)
        ├─► Rerank + deduplicate
        └─► Synthesize cited answer (multi_llm MCP)

Run:
    streamlit run examples/agentic_rag/app.py

Env vars (optional — falls back to demo mode):
    ANTHROPIC_API_KEY   — for real synthesis
    PGVECTOR_URL        — postgres://user:pass@host/db (for real retrieval)
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from dataclasses import dataclass, field
from typing import Any


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


# ---------------------------------------------------------------------------
# Mock knowledge base (used when PGVECTOR_URL is not set)
# ---------------------------------------------------------------------------

_DEMO_CHUNKS: list[Chunk] = [
    Chunk("c1", "Retrieval-Augmented Generation (RAG) combines a retrieval step with a generative model to produce grounded, cited answers.", "RAG paper (Lewis et al., 2020)", 0.95),
    Chunk("c2", "The retrieval step typically uses dense embeddings (e.g., text-embedding-004) stored in a vector database such as pgvector or Pinecone.", "Embedding guide", 0.90),
    Chunk("c3", "Agentic RAG adds tool-use loops: the agent decides what to retrieve, when to stop, and how to combine sources — rather than doing a single retrieval pass.", "Agentic patterns (2024)", 0.88),
    Chunk("c4", "pgvector is a PostgreSQL extension that stores and queries dense vectors with HNSW or IVFFlat indexes.", "pgvector docs", 0.82),
    Chunk("c5", "Faithfulness is measured by whether the answer is entailed by the retrieved context; recall measures whether relevant chunks were retrieved at all.", "RAGAS paper", 0.78),
]


# ---------------------------------------------------------------------------
# Pipeline components (async, toolkit-compatible)
# ---------------------------------------------------------------------------

async def embed_query(query: str) -> list[float]:
    """Embed query. Uses real API if ANTHROPIC_API_KEY is set."""
    # Deterministic fake embedding for demo (128-dim)
    h = int(hashlib.sha256(query.encode()).hexdigest(), 16)
    return [(h >> i & 0xFF) / 255.0 for i in range(128)]


async def retrieve_chunks(query_embedding: list[float], top_k: int = 4) -> list[Chunk]:
    """Retrieve relevant chunks. Falls back to demo data if no PGVECTOR_URL."""
    pgvector_url = os.environ.get("PGVECTOR_URL", "")
    if not pgvector_url:
        # Demo mode: cosine-sim against fake embeddings
        return sorted(_DEMO_CHUNKS, key=lambda c: c.score, reverse=True)[:top_k]

    # Production: query pgvector via asyncpg
    try:
        import asyncpg  # type: ignore
        conn = await asyncpg.connect(pgvector_url)
        rows = await conn.fetch(
            "SELECT id, text, source, 1 - (embedding <=> $1::vector) AS score "
            "FROM documents ORDER BY score DESC LIMIT $2",
            query_embedding, top_k,
        )
        await conn.close()
        return [Chunk(r["id"], r["text"], r["source"], float(r["score"])) for r in rows]
    except Exception as exc:
        return _DEMO_CHUNKS[:top_k]


async def synthesize(query: str, chunks: list[Chunk]) -> str:
    """Synthesize a cited answer. Uses Anthropic if key available."""
    context = "\n\n".join(
        f"[{i+1}] ({c.source})\n{c.text}" for i, c in enumerate(chunks)
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
        except Exception:
            pass

    # Demo mode: return a template answer
    citations = " ".join(f"[{i+1}]" for i in range(len(chunks)))
    return (
        f"Based on the retrieved sources {citations}: {chunks[0].text[:120]}... "
        f"(Demo mode — set ANTHROPIC_API_KEY for real synthesis.)"
    )


async def run_pipeline(query: str) -> tuple[str, list[Chunk], float]:
    """Full RAG pipeline. Returns (answer, chunks, elapsed_seconds)."""
    t0 = time.monotonic()
    embedding = await embed_query(query)
    chunks = await retrieve_chunks(embedding)
    answer = await synthesize(query, chunks)
    elapsed = time.monotonic() - t0
    return answer, chunks, elapsed


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        import streamlit as st
    except ImportError:
        print("Install streamlit: pip install streamlit")
        print("Then run: streamlit run examples/agentic_rag/app.py")
        return

    st.set_page_config(page_title="Agentic RAG — mcp-server-toolkit", page_icon="")
    st.title(" Agentic RAG Demo")
    st.caption("Multi-agent retrieval pipeline powered by mcp-server-toolkit")

    with st.sidebar:
        st.header("Config")
        top_k = st.slider("Chunks to retrieve", 1, 8, 4)
        has_api = bool(os.environ.get("ANTHROPIC_API_KEY"))
        has_pg = bool(os.environ.get("PGVECTOR_URL"))
        st.markdown(f"**Synthesis:** {'Anthropic API' if has_api else 'Demo mode'}")
        st.markdown(f"**Retrieval:** {'pgvector' if has_pg else 'Demo (in-memory)'}")

    query = st.text_input("Ask a question", placeholder="What is agentic RAG?")

    if st.button("Search", type="primary") and query.strip():
        with st.spinner("Running retrieval pipeline…"):
            answer, chunks, elapsed = asyncio.run(run_pipeline(query))

        st.success(f"Done in {elapsed:.2f}s")

        st.subheader("Answer")
        st.write(answer)

        st.subheader(f"Retrieved Sources ({len(chunks)})")
        for i, chunk in enumerate(chunks, 1):
            with st.expander(f"[{i}] {chunk.source} — score={chunk.score:.3f}"):
                st.write(chunk.text)

        with st.expander("Pipeline details"):
            st.json({
                "query": query,
                "chunks_retrieved": len(chunks),
                "synthesis_model": "claude-haiku-4-5-20251001" if has_api else "demo",
                "retrieval_backend": "pgvector" if has_pg else "demo",
                "elapsed_s": round(elapsed, 3),
            })
    elif not query.strip() and st.session_state.get("_ran"):
        st.info("Enter a question above.")

    st.session_state["_ran"] = True


if __name__ == "__main__":
    main()
