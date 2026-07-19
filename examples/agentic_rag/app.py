"""Agentic RAG demo — Streamlit UI over EnhancedMCP-registered pipeline tools.

Run:
    streamlit run examples/agentic_rag/app.py

Env vars (optional — demo mode works without keys):
    ANTHROPIC_API_KEY   — enables live synthesis
    PGVECTOR_URL        — postgres://user:pass@host/db (for pgvector retrieval)
"""

from __future__ import annotations

import asyncio
import uuid

from examples.agentic_rag.pipeline import (
    RateLimiter,
    detect_mode,
    retrieval_backend_label,
    run_pipeline,
)

MAX_REQUESTS_PER_MINUTE = 10


def _session_key() -> str:
    import streamlit as st

    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    return st.session_state.session_id


def main() -> None:
    try:
        import streamlit as st
    except ImportError:
        print("Install streamlit: pip install streamlit")
        print("Then run: streamlit run examples/agentic_rag/app.py")
        return

    mode = detect_mode()
    retrieval_backend = retrieval_backend_label()

    st.set_page_config(page_title="Agentic RAG — mcp-server-toolkit", page_icon="🔍")
    st.title("🔍 Agentic RAG Demo")

    if mode == "live":
        st.success("**Live mode** — Anthropic synthesis enabled")
    else:
        st.info("**Demo mode** — deterministic fixtures, no API keys required")

    st.caption(
        "Multi-agent retrieval pipeline using **EnhancedMCP**-registered tools "
        "(embed_query_tool, retrieve_chunks_tool, synthesize_tool). "
        "Deploy with examples/agentic_rag/render.yaml (Render). "
        "Cold start ~30s on free tier."
    )

    if "rate_limiter" not in st.session_state:
        st.session_state.rate_limiter = RateLimiter(
            max_calls=MAX_REQUESTS_PER_MINUTE,
            window_seconds=60,
        )

    with st.sidebar:
        st.header("Config")
        top_k = st.slider("Chunks to retrieve", 1, 8, 4)
        st.markdown(f"**Mode:** {mode}")
        st.markdown(f"**Synthesis:** {'Anthropic API' if mode == 'live' else 'Demo (template)'}")
        st.markdown(f"**Retrieval:** {retrieval_backend}")
        st.markdown(f"**Rate limit:** {MAX_REQUESTS_PER_MINUTE} req/min per session")

    query = st.text_input("Ask a question", placeholder="What is agentic RAG?")

    if st.button("Search", type="primary") and query.strip():
        limiter: RateLimiter = st.session_state.rate_limiter
        if not limiter.allow(_session_key()):
            st.error(
                f"Rate limit exceeded ({MAX_REQUESTS_PER_MINUTE} requests per minute). "
                "Please wait and try again."
            )
            return

        with st.spinner("Running retrieval pipeline…"):
            answer, chunks, elapsed = asyncio.run(run_pipeline(query, top_k=top_k))

        st.success(f"Done in {elapsed:.2f}s")

        st.subheader("Answer")
        st.write(answer)

        st.subheader(f"Retrieved Sources ({len(chunks)})")
        for i, chunk in enumerate(chunks, 1):
            with st.expander(f"[{i}] {chunk.source} — score={chunk.score:.3f}"):
                st.write(chunk.text)

        with st.expander("Pipeline details"):
            st.json(
                {
                    "query": query,
                    "mode": mode,
                    "chunks_retrieved": len(chunks),
                    "synthesis_model": "claude-haiku-4-5-20251001" if mode == "live" else "demo",
                    "retrieval_backend": retrieval_backend,
                    "mcp_tools": [
                        "embed_query_tool",
                        "retrieve_chunks_tool",
                        "synthesize_tool",
                    ],
                    "elapsed_s": round(elapsed, 3),
                }
            )
    elif not query.strip() and st.session_state.get("_ran"):
        st.info("Enter a question above.")

    st.session_state["_ran"] = True


if __name__ == "__main__":
    main()
