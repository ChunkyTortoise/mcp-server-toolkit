"""pytest integration for quality eval tasks — runs deterministic cases in CI.

All 10 tasks run without API keys. LLM-as-judge scoring is opt-in via
EVAL_JUDGE=1 (nightly workflow only).
"""

from __future__ import annotations

import os

import pytest

from evals.quality.tasks import TASKS


@pytest.mark.parametrize("task", TASKS, ids=[t.id for t in TASKS])
async def test_quality_task(task):
    """Each quality eval task must produce its reference answer."""
    actual = await task.fn()
    assert actual.strip() == task.reference.strip(), (
        f"[{task.id}] {task.description}\n"
        f"  expected: {task.reference!r}\n"
        f"  actual:   {actual!r}"
    )
