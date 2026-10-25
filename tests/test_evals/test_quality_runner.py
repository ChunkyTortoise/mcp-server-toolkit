"""The quality eval runner only writes a file when asked (W5.5)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from evals.quality import runner

RESULTS = Path(runner.__file__).resolve().parent.parent / "RESULTS.md"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.asyncio
async def test_default_run_prints_results_and_leaves_results_md_unchanged(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    before = _digest(RESULTS)

    code = await runner.main([])

    assert code == 0
    assert _digest(RESULTS) == before
    out = capsys.readouterr().out
    assert "# Quality Eval Results" in out
    assert "Results written to" not in out


@pytest.mark.asyncio
async def test_write_results_writes_the_given_path(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    before = _digest(RESULTS)
    target = tmp_path / "results.md"

    code = await runner.main(["--write-results", str(target)])

    assert code == 0
    assert target.read_text().startswith("# Quality Eval Results")
    assert _digest(RESULTS) == before
    assert f"Results written to {target}" in capsys.readouterr().out


def test_write_results_without_a_path_defaults_to_results_md():
    args = runner.build_parser().parse_args(["--write-results"])
    assert args.write_results == runner.DEFAULT_RESULTS_PATH
    assert runner.build_parser().parse_args([]).write_results is None
