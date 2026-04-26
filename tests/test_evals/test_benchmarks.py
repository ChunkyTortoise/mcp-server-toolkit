"""Tests that benchmark scripts run without error."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BENCHMARKS_DIR = Path(__file__).parent.parent.parent / "benchmarks"


def test_bench_cache_script_exists():
    assert (BENCHMARKS_DIR / "bench_cache.py").exists()


def test_bench_cache_runs():
    """bench_cache.py must exit 0 and print cache timing output."""
    result = subprocess.run(
        [sys.executable, str(BENCHMARKS_DIR / "bench_cache.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"bench_cache.py failed:\n{result.stderr}"
    assert "Cache HIT" in result.stdout
    assert "P50" in result.stdout
    assert "Speedup" in result.stdout
