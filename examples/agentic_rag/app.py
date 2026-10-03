"""Standalone RAG walkthrough with explicit fixture boundaries.

Run: streamlit run examples/agentic_rag/app.py

Default: deterministic demo vectors, fixed ranked chunks, template answer.
Optional ANTHROPIC_API_KEY enables synthesis and PGVECTOR_URL enables retrieval.
The demo vectors are not semantic embeddings. This UI does not invoke MCP tools.
Use examples/verified_cache.py for actual tool dispatch and cache telemetry.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import json
from pathlib import Path
import os
import time
from dataclasses import dataclass, field
from typing import Any


logger = logging.getLogger(__name__)


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

FIXTURES = json.loads((Path(__file__).with_name("fixtures.json")).read_text())
_DEMO_CHUNKS = [
    Chunk(item["id"], item["text"], item["source"], item["score"], {"url": item["url"]})
    for item in FIXTURES
]


# ---------------------------------------------------------------------------
# Pipeline components (async, toolkit-compatible)
# ---------------------------------------------------------------------------


async def embed_query(query: str) -> list[float]:
    """Create a deterministic demo vector, not a semantic embedding."""
    # Deterministic fake embedding for demo (128-dim)
    h = int(hashlib.sha256(query.encode()).hexdigest(), 16)
    return [(h >> i & 0xFF) / 255.0 for i in range(128)]


async def retrieve_chunks(query_embedding: list[float], top_k: int = 4) -> list[Chunk]:
    """Retrieve relevant chunks. Falls back to demo data if no PGVECTOR_URL."""
    if not 1 <= top_k <= 8:
        raise ValueError("top_k must be between 1 and 8")
    pgvector_url = os.environ.get("PGVECTOR_URL", "")
    if not pgvector_url:
        # Demo mode: fixed ranking, independent of the query
        return sorted(_DEMO_CHUNKS, key=lambda c: c.score, reverse=True)[:top_k]

    # Production: query pgvector via asyncpg
    try:
        import asyncpg  # type: ignore

        conn = await asyncpg.connect(pgvector_url)
        try:
            rows = await conn.fetch(
                "SELECT id, text, source, 1 - (embedding <=> $1::vector) AS score "
                "FROM documents ORDER BY score DESC LIMIT $2",
                query_embedding,
                top_k,
            )
        finally:
            await conn.close()
        return [Chunk(r["id"], r["text"], r["source"], float(r["score"])) for r in rows]
    except Exception as exc:
        logger.error("Configured retrieval failed (%s)", type(exc).__name__)
        raise RuntimeError("Configured retrieval failed; no fixture fallback was used.") from exc


async def synthesize(query: str, chunks: list[Chunk]) -> str:
    """Synthesize a cited answer. Uses Anthropic if key available."""
    if not chunks:
        return "No sources found. No answer was generated."
    context = "\n\n".join(f"[{i + 1}] ({c.source})\n{c.text}" for i, c in enumerate(chunks))
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

            client = anthropic.AsyncAnthropic(api_key=api_key)
            msg = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text
        except Exception as exc:
            logger.error("Configured synthesis failed (%s)", type(exc).__name__)
            raise RuntimeError(
                "Configured synthesis failed; no fixture fallback was used."
            ) from exc

    # Complete source summaries, each citation supports its adjacent sentence.
    return "Fixture answer, independent of the question; no model call. " + " ".join(
        f"{chunk.text} [{i}]" for i, chunk in enumerate(chunks, 1)
    )


async def run_pipeline(query: str, top_k: int = 4) -> tuple[str, list[Chunk], float]:
    """Full RAG pipeline. Returns (answer, chunks, elapsed_seconds)."""
    t0 = time.monotonic()
    embedding = await embed_query(query)
    chunks = await retrieve_chunks(embedding, top_k=top_k)
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

    st.set_page_config(page_title="RAG walkthrough | MCP toolkit")
    st.title("RAG walkthrough")
    st.caption(
        "Example pipeline: deterministic demo vectors, seeded retrieval and template answers. This UI does not invoke MCP tools."
    )

    with st.sidebar:
        st.header("Config")
        has_api = bool(os.environ.get("ANTHROPIC_API_KEY"))
        has_pg = bool(os.environ.get("PGVECTOR_URL"))
        top_k = st.slider(
            "Maximum sources" if has_pg else "Sources (five fixtures available)",
            1,
            8 if has_pg else len(_DEMO_CHUNKS),
            4,
        )
        st.markdown(f"**Synthesis:** {'Anthropic API' if has_api else 'Stored source summaries'}")
        st.markdown(f"**Retrieval:** {'pgvector' if has_pg else 'Demo (in-memory)'}")

    st.info(
        "Demo retrieval uses five fixed sources and fixed scores, independent of the question. Configured APIs are optional and are not verified by this walkthrough."
    )

    with st.form("rag_question"):
        query = st.text_input("Ask a question", placeholder="What is agentic RAG?", key="question")
        submitted = st.form_submit_button("Search", type="primary")

    submission_notice = st.empty()
    settings_notice = st.empty()
    if submitted:
        if not query.strip():
            submission_notice.info("Enter a question above. The last completed result is retained.")
        else:
            with submission_notice.container(), st.spinner("Running retrieval pipeline..."):
                try:
                    answer, chunks, elapsed = asyncio.run(run_pipeline(query.strip(), top_k=top_k))
                except RuntimeError as exc:
                    submission_notice.error(str(exc))
                else:
                    st.session_state["completed_result"] = {
                        "query": query.strip(),
                        "top_k": top_k,
                        "answer": answer,
                        "chunks": chunks,
                        "elapsed": elapsed,
                        "has_api": has_api,
                        "has_pg": has_pg,
                    }

    result = st.session_state.get("completed_result")
    if result:
        if (result["top_k"], result["has_api"], result["has_pg"]) != (top_k, has_api, has_pg):
            settings_notice.warning(
                "Settings changed. Showing the last completed result; Search runs the new settings."
            )
        st.caption(f"Last completed question: {result['query']}")
        st.success(f"Done in {result['elapsed']:.2f}s")
        st.subheader("Answer")
        st.write(result["answer"])
        st.subheader(f"Retrieved Sources ({len(result['chunks'])})")
        for i, chunk in enumerate(result["chunks"], 1):
            with st.expander(
                f"[{i}] {chunk.source}, score={chunk.score:.3f}",
                key=f"source_{chunk.id}",
                on_change="rerun",
            ):
                st.write(chunk.text)
                if chunk.metadata.get("url"):
                    st.markdown(f"[Source document]({chunk.metadata['url']})")
        with st.expander("Pipeline details", key="pipeline_details", on_change="rerun"):
            st.json(
                {
                    "query": result["query"],
                    "maximum_sources": result["top_k"],
                    "chunks_retrieved": len(result["chunks"]),
                    "synthesis_model": "claude-haiku-4-5-20251001"
                    if result["has_api"]
                    else "stored summaries",
                    "retrieval_backend": "pgvector" if result["has_pg"] else "fixed fixtures",
                    "elapsed_s": round(result["elapsed"], 3),
                }
            )


if __name__ == "__main__":
    main()
