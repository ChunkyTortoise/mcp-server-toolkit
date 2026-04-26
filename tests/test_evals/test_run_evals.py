"""Tests for the eval runner and golden set integrity."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

EVALS_DIR = Path(__file__).parent.parent.parent / "evals"
GOLDEN_PATH = EVALS_DIR / "golden_set.jsonl"


def test_golden_set_exists():
    assert GOLDEN_PATH.exists(), "evals/golden_set.jsonl must exist"


def test_golden_set_valid_jsonl():
    lines = [l for l in GOLDEN_PATH.read_text().splitlines() if l.strip()]
    assert len(lines) > 0, "golden_set.jsonl must not be empty"
    for i, line in enumerate(lines, 1):
        data = json.loads(line)
        assert "id" in data, f"Line {i} missing 'id'"
        assert "description" in data, f"Line {i} missing 'description'"
        assert "tool" in data, f"Line {i} missing 'tool'"


def test_eval_runner_exists():
    assert (EVALS_DIR / "run_evals.py").exists(), "evals/run_evals.py must exist"


def test_eval_runner_passes():
    """Run the eval runner as a subprocess and verify all cases pass."""
    result = subprocess.run(
        [sys.executable, str(EVALS_DIR / "run_evals.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Eval runner exited {result.returncode}.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "All evals passed" in result.stdout


def test_eval_runner_verbose_flag():
    """Verify --verbose flag runs without error."""
    result = subprocess.run(
        [sys.executable, str(EVALS_DIR / "run_evals.py"), "--verbose"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "[PASS]" in result.stdout


def test_no_duplicate_eval_ids():
    lines = [l for l in GOLDEN_PATH.read_text().splitlines() if l.strip()]
    ids = [json.loads(l)["id"] for l in lines]
    assert len(ids) == len(set(ids)), "Duplicate eval IDs found in golden_set.jsonl"
