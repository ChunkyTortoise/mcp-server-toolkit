# Agentic RAG Demo

Dual-mode retrieval-augmented generation demo for **mcp-server-toolkit**. The pipeline registers `embed_query_tool`, `retrieve_chunks_tool`, and `synthesize_tool` on an `EnhancedMCP` server — the Streamlit UI runs the same logic locally.

## Modes

| Mode | Trigger | Behavior |
|------|---------|----------|
| **Demo** (default) | No `ANTHROPIC_API_KEY` | Deterministic embeddings, in-memory chunks, template synthesis with citations |
| **Live** | `ANTHROPIC_API_KEY` set | Anthropic synthesis; falls back to demo template on API errors |

Optional: set `PGVECTOR_URL` (`postgres://…`) to use pgvector for retrieval instead of the in-memory fixture set.

## Local run

From the repo root:

```bash
# Install toolkit + demo deps
uv sync
uv pip install streamlit anthropic

# Demo mode (no keys)
streamlit run examples/agentic_rag/app.py

# Live synthesis
export ANTHROPIC_API_KEY=sk-ant-...
streamlit run examples/agentic_rag/app.py
```

Run pipeline unit tests:

```bash
uv run pytest tests/examples/test_agentic_rag_pipeline.py -q
```

## Deploy (Render)

1. Create a **Web Service** from this repo.
2. Use `examples/agentic_rag/render.yaml` as a blueprint, or set manually:
   - **Build:** `pip install -r examples/agentic_rag/requirements-demo.txt && pip install -e .`
   - **Start:** `streamlit run examples/agentic_rag/app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true`
3. Set `PYTHON_VERSION=3.12`.
4. Optionally add `ANTHROPIC_API_KEY` in the Render dashboard for live synthesis.

**Cold start:** Free-tier services spin down after inactivity. The first request after idle may take ~30 seconds while the container wakes up.

## Architecture

```
Streamlit UI
    │
    ├─► embed_query_tool      (EnhancedMCP)
    ├─► retrieve_chunks_tool  (EnhancedMCP)
    └─► synthesize_tool       (EnhancedMCP)
```

Core logic lives in `pipeline.py` for testability; tools are thin wrappers registered on `EnhancedMCP("agentic-rag-demo")`.
