"""Unit tests for agentic RAG dual-mode pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from examples.agentic_rag.pipeline import (  # noqa: E402
    DEMO_CHUNKS,
    RateLimiter,
    detect_mode,
    run_pipeline,
    synthesize,
)


def test_detect_mode_demo_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PGVECTOR_URL", raising=False)
    assert detect_mode() == "demo"


def test_detect_mode_live_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    assert detect_mode() == "live"


@pytest.mark.asyncio
async def test_demo_synthesize_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    answer = await synthesize("What is agentic RAG?", DEMO_CHUNKS[:2])
    assert "Demo mode" in answer
    assert "[1]" in answer


def test_rate_limiter_blocks_after_max() -> None:
    limiter = RateLimiter(max_calls=2, window_seconds=60)
    assert limiter.allow("session-a") is True
    assert limiter.allow("session-a") is True
    assert limiter.allow("session-a") is False
    assert limiter.allow("session-b") is True


@pytest.mark.asyncio
async def test_run_pipeline_demo_returns_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PGVECTOR_URL", raising=False)
    answer, chunks, elapsed = await run_pipeline("What is RAG?", top_k=3)
    assert len(chunks) == 3
    assert "Demo mode" in answer
    assert elapsed >= 0

@pytest.mark.asyncio
async def test_run_pipeline_demo_answer_includes_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PGVECTOR_URL", raising=False)
    answer, chunks, _elapsed = await run_pipeline("What is agentic RAG?", top_k=4)
    assert len(chunks) >= 1
    assert "Demo mode" in answer
    assert "[1]" in answer
    assert "[2]" in answer

