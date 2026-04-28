#!/usr/bin/env python3
"""Quality eval runner — executes tasks and optionally scores with LLM-as-judge.

Usage:
    python evals/quality/runner.py                 # deterministic tasks only
    python evals/quality/runner.py --judge         # + LLM-as-judge scoring (needs ANTHROPIC_API_KEY)
    python evals/quality/runner.py --category auth # filter by category
    python evals/quality/runner.py --output evals/RESULTS.md  # write results

Exit code 1 if any deterministic task fails.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from evals.quality.judge import JudgeScore, judge
from evals.quality.tasks import TASKS, EvalTask


@dataclass
class TaskResult:
    task: EvalTask
    actual: str
    passed: bool
    score: JudgeScore | None
    elapsed_ms: float
    error: str = ""


async def run_task(task: EvalTask, use_judge: bool) -> TaskResult:
    t0 = time.perf_counter()
    try:
        actual = await task.fn()
        elapsed = (time.perf_counter() - t0) * 1000
        passed = actual.strip() == task.reference.strip()
        score: JudgeScore | None = None
        if use_judge:
            score = await judge(
                task_description=task.description,
                reference=task.reference,
                response=actual,
            )
        return TaskResult(task=task, actual=actual, passed=passed, score=score, elapsed_ms=elapsed)
    except Exception as exc:
        elapsed = (time.perf_counter() - t0) * 1000
        return TaskResult(task=task, actual="", passed=False, score=None, elapsed_ms=elapsed, error=str(exc))


def _format_score(score: JudgeScore | None) -> str:
    if score is None:
        return ""
    return f"  judge: {score.mean:.1f}/5 (C={score.correctness} F={score.faithfulness} H={score.helpfulness} Cn={score.conciseness})"


def _write_results(results: list[TaskResult], output_path: Path, use_judge: bool) -> None:
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    total_ms = sum(r.elapsed_ms for r in results)

    lines = [
        "# Quality Eval Results",
        "",
        f"Last run: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}",
        f"Mode: {'deterministic + LLM-as-judge' if use_judge else 'deterministic only'}",
        "",
        "## Summary",
        "",
        f"**{passed}/{total} tasks passed** | Elapsed: {total_ms:.0f}ms",
        "",
    ]

    if use_judge:
        scored = [r for r in results if r.score]
        if scored:
            means = [r.score.mean for r in scored]
            p50 = sorted(means)[len(means) // 2]
            p95 = sorted(means)[int(len(means) * 0.95)] if len(means) > 1 else means[0]
            lines += [
                "### LLM-as-Judge Scores (1–5)",
                "",
                f"| Metric | Value |",
                f"|--------|-------|",
                f"| P50 quality | {p50:.2f} |",
                f"| P95 quality | {p95:.2f} |",
                f"| Mean quality | {sum(means)/len(means):.2f} |",
                "",
            ]

    # Group by category
    categories: dict[str, list[TaskResult]] = {}
    for r in results:
        categories.setdefault(r.task.category, []).append(r)

    lines.append("## Results by Category")
    lines.append("")

    for cat, cat_results in categories.items():
        cat_passed = sum(1 for r in cat_results if r.passed)
        lines.append(f"### {cat.capitalize()} ({cat_passed}/{len(cat_results)})")
        lines.append("")
        lines.append("```")
        for r in cat_results:
            status = "PASS" if r.passed else "FAIL"
            line = f"  [{status}] {r.task.id}: {r.task.description}"
            if not r.passed:
                line += f"\n         expected: {r.task.reference!r}"
                line += f"\n         actual:   {r.actual!r}"
            if r.error:
                line += f"\n         error:    {r.error}"
            judge_str = _format_score(r.score)
            if judge_str:
                line += f"\n  {judge_str}"
            lines.append(line)
        lines.append("```")
        lines.append("")

    lines += [
        "## Reproducing",
        "",
        "```bash",
        "# Deterministic only (no API key needed):",
        "python evals/quality/runner.py",
        "",
        "# With LLM-as-judge scoring:",
        "ANTHROPIC_API_KEY=sk-... python evals/quality/runner.py --judge",
        "```",
        "",
        "## Coverage",
        "",
        "| Category | Cases | What it tests |",
        "|----------|-------|----------------|",
        "| routing  | 3     | Provider selection priority, circuit-breaker trip |",
        "| costing  | 2     | Per-model pricing accuracy |",
        "| auth     | 3     | JWT validation (valid, expired, wrong secret) |",
        "| cache    | 2     | Hit/miss semantics, key determinism |",
    ]

    output_path.write_text("\n".join(lines) + "\n")


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="mcp-server-toolkit quality evals")
    parser.add_argument("--judge", action="store_true", help="Enable LLM-as-judge scoring")
    parser.add_argument("--category", help="Filter tasks by category")
    parser.add_argument("--output", default="evals/RESULTS.md", help="Output path for results markdown")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    tasks = TASKS
    if args.category:
        tasks = [t for t in tasks if t.category == args.category]

    print(f"mcp-server-toolkit quality evals -- {len(tasks)} tasks")
    if args.judge:
        import os
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        print(f"LLM-as-judge: {'enabled (real)' if key else 'enabled (mock — set ANTHROPIC_API_KEY for real scores)'}")

    results = []
    for task in tasks:
        result = await run_task(task, use_judge=args.judge)
        results.append(result)
        status = "PASS" if result.passed else "FAIL"
        suffix = f" [{result.elapsed_ms:.1f}ms]"
        if args.verbose or not result.passed:
            print(f"  [{status}] {task.id}: {task.description}{suffix}")
            if not result.passed:
                print(f"         expected: {task.reference!r}")
                print(f"         actual:   {result.actual!r}")
            if result.score:
                print(f"         judge: {result.score.mean:.1f}/5")
        else:
            print(f"  [{status}] {task.id}{suffix}")

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"\n{passed}/{total} passed")

    output_path = Path(args.output)
    _write_results(results, output_path, use_judge=args.judge)
    print(f"Results written to {output_path}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
