"""Exercise the public no-key demo and error boundaries."""

import sys
import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import importlib.util

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rag_audit_app", ROOT / "examples/agentic_rag/app.py")
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)
run_demo = runpy.run_path(str(ROOT / "examples/verified_cache.py"))["run_demo"]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PGVECTOR_URL", raising=False)


async def test_public_cache_demo_dispatches_twice_executes_once():
    result = await run_demo()
    assert result["results"] == ["Hello, World!", "Hello, World!"]
    assert result["tool_executions"] == 1
    assert [span["attributes"]["cache_hit"] for span in result["spans"]] == [False, True]


async def test_pipeline_honors_selected_chunk_count():
    answer, chunks, elapsed = await app.run_pipeline("What is RAG?", top_k=2)
    assert len(chunks) == 2
    assert "[1] [2]" in answer
    assert elapsed >= 0


async def test_empty_retrieval_does_not_crash_or_invent_answer(monkeypatch):
    monkeypatch.setattr(app, "retrieve_chunks", AsyncMock(return_value=[]))
    answer, chunks, _ = await app.run_pipeline("missing")
    assert chunks == []
    assert answer == "No sources found. No answer was generated."


async def test_retrieval_error_is_explicit_and_connection_closes(monkeypatch):
    monkeypatch.setenv("PGVECTOR_URL", "postgres://invalid-fixture")
    conn = SimpleNamespace(fetch=AsyncMock(side_effect=ValueError("test")), close=AsyncMock())
    monkeypatch.setitem(
        sys.modules, "asyncpg", SimpleNamespace(connect=AsyncMock(return_value=conn))
    )
    with pytest.raises(RuntimeError, match="no fixture fallback"):
        await app.run_pipeline("failure")
    conn.close.assert_awaited_once()


async def test_synthesis_error_is_explicit(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-placeholder")
    client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(side_effect=ValueError())))
    monkeypatch.setitem(
        sys.modules, "anthropic", SimpleNamespace(AsyncAnthropic=lambda **kw: client)
    )
    with pytest.raises(RuntimeError, match="no fixture fallback"):
        await app.run_pipeline("failure")
