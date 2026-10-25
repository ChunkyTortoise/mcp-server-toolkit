#!/usr/bin/env python3
"""Check ``docs/claims.yaml`` against the repository.

Three checks, in increasing cost:

1. **Schema.** Every claim has an id, statement, value, match tokens, a
   reproduction command, a date, a status and a scope. Ids are unique, dates
   are ISO, and each claim names an artifact that exists (or a ``url``).
2. **Artifact.** With ``artifact_check: contains`` the claim's value must
   appear in the artifact file (whitespace- and case-insensitive). This is
   what catches a doc that changed under a registered number.
3. **Execution.** With ``--run`` (all runnable claims) or ``--sample N``
   (a deterministic subset) each claim's ``command`` is executed: it must exit
   0 and print its ``expect`` text (defaults to ``value``). Claims marked
   ``executes: false``, or ``network: true`` without ``--include-network``,
   are skipped and reported as skipped, never as passed.

Coverage: every metric-bearing number in ``docs_scanned`` must resolve to a
claim's ``match`` token or to an allowance. An allowance matches the **token**
(not the line), and may be narrowed to one file with ``where``. There is no
numeric or "same number with a unit" fallback: ``match`` must be exact.

Exit codes: ``0`` when nothing blocking was found, ``1`` when a check failed.
Without ``--check``, ``--run`` or ``--sample`` the script only reports and
exits 0; pass ``--check`` to make it a gate. ``--strict`` also fails on
``stale``, ``retracted`` and ``illustrative`` claims.

Limits, deliberately stated: the coverage scan is lexical. It finds numbers
carrying a unit, a currency sign, or a bold number alone in a table cell. It
will not find a number written as a word, a comparative with no number, or a
claim in a file not listed in ``docs_scanned``. Fenced code blocks are
skipped. ``--sample`` is a sample, not a guarantee of the claims it did not
pick.

Usage::

    python scripts/check_claims.py                 # report only
    python scripts/check_claims.py --check         # gate: exit 1 on failure
    python scripts/check_claims.py --check --strict
    python scripts/check_claims.py --sample 10     # execute 10 runnable claims
    python scripts/check_claims.py --list-tokens
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import random
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs" / "claims.yaml"

REQUIRED_KEYS = ("id", "statement", "value", "match", "command", "date", "status", "scope")
VALID_STATUSES = (
    "verified",
    "historical",
    "ci_gate",
    "inventory",
    "illustrative",
    "stale",
    "retracted",
)
WARN_STATUSES = ("stale", "retracted", "illustrative")
ARTIFACT_CHECKS = ("exists", "contains")

_NUM = r"\d[\d,]*(?:\.\d+)?"
_UNITS = (
    r"%|ms|s|x|MB|GB|KB|LOC|USD|tokens|tests|test|cases|case|servers|server|"
    r"lines|line|files|file|iterations|warmup|calls|call|days|day|weeks|week|"
    r"hours|hour|minutes|minute|seconds|second|passed|skipped|queries|query|tasks"
)
# Concatenated, not nested in an f-string: "${_NUM}" in an f-string is a literal
# dollar sign followed by the substitution, which anchors the pattern to nothing.
_UNIT_RE = re.compile(r"(?<![\w.])(?P<num>" + _NUM + r")\s*(?P<unit>" + _UNITS + r")(?!\w)", re.I)
_CURRENCY_RE = re.compile(r"\$\s?(?P<num>" + _NUM + r")")
_TABLE_RE = re.compile(r"\|\s*\*{0,2}(?P<num>" + _NUM + r")\*{0,2}\s*\|")


@dataclass
class Problem:
    level: str  # "FAIL" or "WARN"
    where: str
    message: str


def contains_value(needle: object, haystack: str) -> bool:
    """True when ``needle`` appears in ``haystack`` as a whole number.

    Case, commas and whitespace inside the needle are ignored ("0.007 ms"
    matches "0.007ms"), but a needle that starts or ends with a digit must not
    touch another digit: "8" does not match "18", and "0.42" does not match
    "0.425". A plain substring test let a count of 18 pass a claim of 8.
    """
    flat = re.sub(r"\s+", "", str(needle)).lower().replace(",", "")
    if not flat:
        return False
    pattern = r"\s*".join(re.escape(char) for char in flat)
    if flat[0].isdigit():
        pattern = r"(?<![\d.])" + pattern
    if flat[-1].isdigit():
        pattern += r"(?!\d|\.\d)"
    return re.search(pattern, str(haystack).lower().replace(",", "")) is not None


def load_ledger(path: Path) -> dict:
    try:
        import yaml
    except ImportError:  # pragma: no cover - environment guard
        sys.stderr.write(
            "check_claims: PyYAML is required (it is in the [dev] extra).\n"
            "Install it with: pip install -e '.[dev]'\n"
        )
        raise SystemExit(3)
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping at the top level")
    return data


def validate_claims(ledger: dict) -> tuple[list[Problem], list[dict]]:
    problems: list[Problem] = []
    claims = ledger.get("claims")
    if not isinstance(claims, list) or not claims:
        return [Problem("FAIL", "docs/claims.yaml", "`claims` must be a non-empty list")], []

    valid: list[dict] = []
    seen: set[str] = set()
    for index, claim in enumerate(claims):
        where = f"claims[{index}]"
        if not isinstance(claim, dict):
            problems.append(Problem("FAIL", where, "entry must be a mapping"))
            continue
        claim_id = claim.get("id")
        if isinstance(claim_id, str) and claim_id:
            where = f"claim {claim_id!r}"
            if claim_id in seen:
                problems.append(Problem("FAIL", where, "duplicate id"))
            seen.add(claim_id)
        missing = [key for key in REQUIRED_KEYS if key not in claim]
        if missing:
            problems.append(Problem("FAIL", where, f"missing required key(s) {missing}"))
            continue

        if not isinstance(claim["match"], list) or not claim["match"]:
            problems.append(Problem("FAIL", where, "`match` must be a non-empty list of tokens"))
        if claim["status"] not in VALID_STATUSES:
            problems.append(
                Problem("FAIL", where, f"status {claim['status']!r} not in {VALID_STATUSES}")
            )
        try:
            date.fromisoformat(str(claim["date"]))
        except ValueError:
            problems.append(Problem("FAIL", where, f"date {claim['date']!r} is not YYYY-MM-DD"))

        artifact = claim.get("artifact")
        if isinstance(artifact, str) and artifact:
            artifact_path = ROOT / artifact
            if not artifact_path.exists():
                problems.append(Problem("FAIL", where, f"artifact {artifact!r} does not exist"))
        elif not claim.get("url"):
            problems.append(Problem("FAIL", where, "needs an `artifact` that exists, or a `url`"))

        check = claim.get("artifact_check", "exists")
        if check not in ARTIFACT_CHECKS:
            problems.append(
                Problem("FAIL", where, f"artifact_check {check!r} not in {ARTIFACT_CHECKS}")
            )
        if check == "contains" and not artifact:
            problems.append(
                Problem("FAIL", where, "artifact_check: contains needs an `artifact` file")
            )

        if claim["status"] in WARN_STATUSES:
            problems.append(
                Problem(
                    "WARN",
                    where,
                    f"status {claim['status']}: {claim.get('action', 'must be removed or re-measured')}",
                )
            )
        valid.append(claim)
    return problems, valid


def check_artifacts(claims: list[dict]) -> list[Problem]:
    """Verify `artifact_check: contains` claims against their artifact file."""
    problems: list[Problem] = []
    for claim in claims:
        if claim.get("artifact_check", "exists") != "contains":
            continue
        path = ROOT / str(claim["artifact"])
        if not path.is_file():
            problems.append(
                Problem(
                    "FAIL",
                    f"claim {claim['id']!r}",
                    f"artifact {claim['artifact']!r} is not a file",
                )
            )
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            problems.append(
                Problem(
                    "FAIL", f"claim {claim['id']!r}", f"artifact {claim['artifact']!r} is not text"
                )
            )
            continue
        found = contains_value(claim["value"], body)
        if not found:
            # Always a failure, whatever the status: the ledger and the artifact
            # disagree, so the registered number no longer describes the doc. A
            # warning here let an edited extrapolation pass `--check`.
            problems.append(
                Problem(
                    "FAIL",
                    f"claim {claim['id']!r}",
                    f"value {claim['value']!r} does not appear in {claim['artifact']!r}"
                    " (update the claim, or retire it if the number is gone)",
                )
            )
    return problems


def strip_code_fences(text: str) -> list[str]:
    """Return lines with fenced code blocks blanked out (line numbers preserved)."""
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return out


def extract_tokens(text: str) -> list[tuple[str, int, str]]:
    """Return (token, line number, line) for every metric-bearing number.

    The token keeps its unit, so ``626 passed`` and ``626`` are distinct, and a
    claim's ``match`` entry must use the same form.
    """
    found: list[tuple[str, int, str]] = []
    for line_no, line in enumerate(strip_code_fences(text), start=1):
        if not line.strip():
            continue
        tokens = [
            f"{m.group('num')}{m.group('unit')}"
            if m.group("unit") in {"%", "x"}
            else f"{m.group('num')} {m.group('unit')}"
            for m in _UNIT_RE.finditer(line)
        ]
        tokens.extend(f"${m.group('num')}" for m in _CURRENCY_RE.finditer(line))
        tokens.extend(m.group("num") for m in _TABLE_RE.finditer(line))
        for token in tokens:
            found.append((normalise(token), line_no, line.strip()))
    return found


def normalise(token: str) -> str:
    return re.sub(r"\s+", " ", str(token)).strip().lower().replace(",", "")


def check_coverage(ledger: dict) -> tuple[list[Problem], int]:
    problems: list[Problem] = []
    known: set[str] = set()
    for claim in ledger.get("claims") or []:
        if isinstance(claim, dict):
            known.update(normalise(token) for token in claim.get("match") or [])

    allowances = []
    for entry in ledger.get("allow") or []:
        if not isinstance(entry, dict) or "token" not in entry or "reason" not in entry:
            problems.append(
                Problem("FAIL", "docs/claims.yaml", "each `allow` entry needs `token` and `reason`")
            )
            continue
        try:
            pattern = re.compile(entry["token"])
        except re.error as exc:
            problems.append(
                Problem("FAIL", "docs/claims.yaml", f"bad allow token {entry['token']!r}: {exc}")
            )
            continue
        allowances.append((pattern, entry.get("where"), entry["reason"]))

    docs = ledger.get("docs_scanned") or []
    if not docs:
        problems.append(
            Problem("FAIL", "docs/claims.yaml", "`docs_scanned` must list at least one file")
        )

    total = 0
    for relative in docs:
        doc_path = ROOT / relative
        if not doc_path.exists():
            problems.append(Problem("FAIL", relative, "scanned document does not exist"))
            continue
        for token, line_no, line in extract_tokens(doc_path.read_text(encoding="utf-8")):
            total += 1
            if token in known:
                continue
            if any(
                pattern.fullmatch(token) and (not scope or fnmatch.fnmatch(relative, scope))
                for pattern, scope, _reason in allowances
            ):
                continue
            problems.append(
                Problem(
                    "FAIL",
                    f"{relative}:{line_no}",
                    f"number {token!r} has no ledger entry (add a claim, or a token-scoped `allow`)",
                )
            )
    return problems, total


def published_tokens(ledger: dict) -> set[str]:
    """Every token the coverage scan finds in ``docs_scanned``."""
    tokens: set[str] = set()
    for relative in ledger.get("docs_scanned") or []:
        path = ROOT / relative
        if path.exists():
            tokens.update(
                token for token, _line_no, _line in extract_tokens(path.read_text(encoding="utf-8"))
            )
    return tokens


def skip_reason(claim: dict, args: argparse.Namespace, published: set[str] | None) -> str | None:
    """Why a claim is not executed, or None when it should run."""
    if str(claim["command"]).startswith("none"):
        return "not runnable (command starts with 'none')"
    if not claim.get("executes", True):
        return "executes: false"
    if claim.get("network") and not args.include_network:
        return "needs --include-network"
    if published is not None and not any(normalise(token) in published for token in claim["match"]):
        return "not published in docs_scanned (--published)"
    return None


def run_claims(claims: list[dict], ledger: dict, args: argparse.Namespace) -> list[Problem]:
    """Execute claim commands; return problems for the ones that fail."""
    published = published_tokens(ledger) if args.published else None
    reasons = {claim["id"]: skip_reason(claim, args, published) for claim in claims}
    runnable = [claim for claim in claims if reasons[claim["id"]] is None]

    selected = runnable
    if args.sample is not None:
        if args.sample > len(runnable):
            sys.stderr.write(
                f"check_claims: --sample {args.sample} exceeds {len(runnable)} runnable claims\n"
            )
        # Seeded by date unless --seed is given, so the sample rotates from day
        # to day but a given run can be reproduced.
        print(f"[INFO] --sample {args.sample} with --seed {args.seed}")
        selected = random.Random(args.seed).sample(runnable, min(args.sample, len(runnable)))
        for claim in runnable:
            if claim not in selected:
                reasons[claim["id"]] = "not selected by --sample"
    skipped = [claim for claim in claims if claim not in selected]

    # Pin `python` in the ledger's commands to the interpreter running this
    # script, so the same ledger works in .venv, CI and a bare interpreter.
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), env.get("PATH", "")])

    problems: list[Problem] = []
    for claim in sorted(selected, key=lambda item: item["id"]):
        command = str(claim["command"])
        expected = claim.get("expect", claim["value"])
        try:
            result = subprocess.run(  # noqa: S602 - the ledger is repo-controlled content
                command,
                shell=True,
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=args.timeout,
            )
        except subprocess.TimeoutExpired:
            problems.append(
                Problem("FAIL", f"claim {claim['id']!r}", f"timed out after {args.timeout}s")
            )
            continue
        output = result.stdout + result.stderr
        if result.returncode != 0:
            tail = (result.stdout + result.stderr).strip().splitlines()[-1:] or ["no output"]
            problems.append(
                Problem(
                    "FAIL",
                    f"claim {claim['id']!r}",
                    f"command exited {result.returncode}: {tail[0][:160]}",
                )
            )
        elif not contains_value(expected, output):
            problems.append(
                Problem(
                    "FAIL",
                    f"claim {claim['id']!r}",
                    f"expected {expected!r} in the output; got "
                    f"{(result.stdout or result.stderr).strip().splitlines()[-1:] or ['nothing']}",
                )
            )
        else:
            print(f"[PASS] claim {claim['id']!r}: {command}")

    for claim in sorted(skipped, key=lambda item: item["id"]):
        print(f"[SKIP] claim {claim['id']!r}: {reasons[claim['id']]}")
    return problems


def list_tokens(ledger: dict, only: str | None) -> None:
    known: set[str] = set()
    for claim in ledger.get("claims") or []:
        known.update(normalise(token) for token in claim.get("match") or [])
    docs = [only] if only else (ledger.get("docs_scanned") or [])
    for relative in docs:
        path = ROOT / relative
        if not path.exists():
            print(f"missing: {relative}")
            continue
        print(f"--- {relative}")
        seen: set[tuple[str, int]] = set()
        for token, line_no, line in extract_tokens(path.read_text(encoding="utf-8")):
            if (token, line_no) in seen:
                continue
            seen.add((token, line_no))
            mark = "ledger" if token in known else "UNLEDGERED"
            print(f"  {line_no:>4}  {token:<14} {mark:<11} {line[:90]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="gate: exit 1 when a check fails")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="also fail on stale/retracted/illustrative claims (use before a release or deploy)",
    )
    parser.add_argument("--run", action="store_true", help="execute every runnable claim command")
    parser.add_argument(
        "--sample",
        type=int,
        metavar="N",
        help="execute N runnable claims, chosen deterministically",
    )
    parser.add_argument(
        "--include-network", action="store_true", help="also run claims marked network: true"
    )
    parser.add_argument(
        "--published",
        action="store_true",
        help="with --run/--sample, execute only claims whose tokens appear in docs_scanned (the CI mode)",
    )
    parser.add_argument(
        "--seed", default=date.today().isoformat(), help="seed for --sample (default: today's date)"
    )
    parser.add_argument(
        "--timeout", type=int, default=180, help="per-command timeout in seconds (default 180)"
    )
    parser.add_argument(
        "--list-tokens",
        nargs="?",
        const="",
        metavar="DOC",
        help="show every token and its ledger status",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable summary on stdout")
    args = parser.parse_args(argv)

    if not LEDGER.exists():
        sys.stderr.write(f"check_claims: {LEDGER} not found\n")
        return 1
    ledger = load_ledger(LEDGER)

    if args.list_tokens is not None:
        list_tokens(ledger, args.list_tokens or None)
        return 0

    problems, claims = validate_claims(ledger)
    problems.extend(check_artifacts(claims))
    coverage_problems, token_count = check_coverage(ledger)
    problems.extend(coverage_problems)
    if args.run or args.sample is not None:
        problems.extend(run_claims(claims, ledger, args))
    elif not args.check:
        print("[INFO] commands were not executed; pass --run or --sample N to execute them")

    if args.strict:
        problems = [
            Problem("FAIL", p.where, p.message) if p.level == "WARN" else p for p in problems
        ]

    failing = [p for p in problems if p.level == "FAIL"]
    warnings = [p for p in problems if p.level == "WARN"]
    for problem in problems:
        print(f"[{problem.level}] {problem.where}: {problem.message}")

    enforced = args.check or args.strict or args.run or args.sample is not None
    summary = {
        "claims": len(claims),
        "tokens": token_count,
        "failures": len(failing),
        "warnings": len(warnings),
        "enforced": enforced,
        "strict": args.strict,
    }
    if args.json:
        import json

        print(json.dumps(summary))
    else:
        print(
            f"\nclaims: {summary['claims']}  scanned tokens: {summary['tokens']}  "
            f"failures: {summary['failures']}  warnings: {summary['warnings']}  "
            f"enforced: {summary['enforced']}  strict: {summary['strict']}"
        )
    if failing and enforced:
        print("RESULT: FAIL")
        return 1
    print("RESULT: OK" if not failing else "RESULT: OK (report only; pass --check to enforce)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
