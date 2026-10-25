#!/usr/bin/env python3
"""Quality eval runner - executes tasks and optionally scores with LLM-as-judge.

Usage:
    python evals/quality/runner.py                 # deterministic tasks only
    python evals/quality/runner.py --judge         # + LLM-as-judge scoring (needs ANTHROPIC_API_KEY)
    python evals/quality/runner.py --category auth # filter by category
    python evals/quality/runner.py --write-results # also write evals/RESULTS.md
    python evals/quality/runner.py --write-results out.md  # write to another path

Without --write-results the results markdown goes to stdout and no file changes.

Exit code 1 if any deterministic task fails.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from evals.quality.judge import JudgeScore, judge
from evals.quality.tasks import TASKS, EvalTask

DEFAULT_RESULTS_PATH = "evals/RESULTS.md"


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


def _render_results(results: list[TaskResult], use_judge: bool) -> str:
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
                "### LLM-as-Judge Scores (1-5)",
                "",
                "| Metric | Value |",
                "|--------|-------|",
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

    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="mcp-server-toolkit quality evals")
    parser.add_argument("--judge", action="store_true", help="Enable LLM-as-judge scoring")
    parser.add_argument("--category", help="Filter tasks by category")
    parser.add_argument(
        "--write-results",
        "--output",
        dest="write_results",
        nargs="?",
        const=DEFAULT_RESULTS_PATH,
        metavar="PATH",
        help=f"Write results markdown to PATH (default {DEFAULT_RESULTS_PATH}); stdout otherwise",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser


async def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    tasks = TASKS
    if args.category:
        tasks = [t for t in tasks if t.category == args.category]

    print(f"mcp-server-toolkit quality evals -- {len(tasks)} tasks")
    use_judge = args.judge
    if use_judge:
        import os
        if os.environ.get("ANTHROPIC_API_KEY", ""):
            print("LLM-as-judge: enabled")
        else:
            print("judge: skipped (no ANTHROPIC_API_KEY)")
            use_judge = False

    results = []
    for task in tasks:
        result = await run_task(task, use_judge=use_judge)
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

    report = _render_results(results, use_judge=use_judge)
    if args.write_results:
        output_path = Path(args.write_results)
        output_path.write_text(report)
        print(f"Results written to {output_path}")
    else:
        print()
        print(report, end="")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
