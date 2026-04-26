# mcp-server-toolkit Audit -- 2026-04-25 (Cycle 2)

**Method**: Self-triage (GPT-5.5-thinking unavailable; Grok MCP 403). Applying the 5-dimension rubric from `~/.claude/reference/audit-prompts/gpt55-senior-ai-engineer-reviewer.md` against current repo state.

**Previous cycle**: Cycle 1 (prior session) shipped ADRs 0001-0003, evals golden set (10 cases), benchmarks, model name fixes, pyright fixes. Score went from 23/50 to ~29/50 per prior REPORT.md.

---

## Scores (current state, 2026-04-25)

| Dimension | Score | Justification |
|---|---|---|
| Hiring signal density | 7/10 | PyPI published, For Hiring Managers table, cache benchmarks with reproducible commands (bench_cache.py, P50 0.007ms), 3 ADRs with genuine tradeoff reasoning. Undercut by stale README test count (claims 412, actual 383 collect) and static coverage badge (hardcoded "88%", not live Codecov). Both are falsifiable in <60 seconds. |
| Architecture clarity | 7/10 | ADRs 0001-0003 each state Y-over-Z rationale explicitly: inheritance vs composition, tiered vs single-tier cache, per-provider vs global breaker. Mermaid diagram present. Gap: no ADR for A2A adapter (the most novel feature); optional dep strategy (sqlglot not in dev default) undocumented. |
| Eval quality | 4/10 | 10 routing evals for multi_llm server (100% pass, stub providers, one command: `python evals/run_evals.py`). But only 1 of 9 servers has eval coverage; no CI gate (evals never run on push); no adversarial cases; no evals for caching correctness or A2A adapter protocol compliance. |
| Agent-native depth | 8/10 | Strongest dimension: per-provider circuit breakers (ADR-0003), L1/L2 cache (ADR-0002), OpenTelemetry, rate limiting, API key auth, MCPTestClient, A2A adapter. Non-blocking pyright (`continue-on-error: true` in CI, commit e8d64ab) and absent retry-with-backoff before circuit trip are visible gaps. |
| README and docs clarity | 7/10 | "Proof in 30 seconds" block and For Hiring Managers table land well. Quick Start is clean. "Production-ready" in opener is an unsupported assertion. Static "88%" coverage badge and stale "412 tests" chip credibility for a reviewer who runs the tests. No DEMO.md or live demo link. |
| **Total** | **33/50** | |

---

## P0 Issues (must fix this cycle)

1. **Stale test count in README** -- `README.md` (hero Proof block + For Hiring Managers table). "412 tests" appears twice but only 383 collect (`pytest --collect-only -q` shows 3 collection errors). Root cause: `tests/test_database_query/` requires `sqlglot` (optional `[database]` extra), not installed in default dev. Fix: add `pytest.importorskip("sqlglot")` at module level in `tests/test_database_query/test_schema_inspector.py`, `test_server.py`, `test_sql_generator.py` so they auto-skip when the extra is absent; recount and update README. Effort: S. Verification: `pytest --collect-only -q 2>&1 | grep -E "collected|error"` shows 0 errors.

2. **Test collection errors on every local run** -- `tests/test_database_query/test_schema_inspector.py`, `test_server.py`, `test_sql_generator.py`. `ModuleNotFoundError: No module named 'sqlglot'` causes 3 red collection errors in any `pytest tests/` run without the `[database]` extra installed. This is the same fix as P0-1. Effort: S (same fix). Verification: `pytest -x -q 2>&1 | grep -c "error"` returns 0.

3. **Evals not gated in CI** -- `.github/workflows/ci.yml`. `evals/run_evals.py` passes 10/10 but is never run in CI -- any push can silently break multi_llm routing logic. The evals use stub providers (no API keys required) so cost is zero. Fix: add a step `python evals/run_evals.py` to the CI workflow after tests. Effort: S. Verification: `gh run list --limit 1` shows an eval step in the run.

4. **Coverage floor not enforced** -- `pyproject.toml`. `[tool.pytest.ini_options]` has no `--cov-fail-under`. The README badge is a hardcoded string (`img.shields.io/badge/coverage-88%25`), not a live Codecov badge. Fix: add `addopts = "--cov=mcp_toolkit --cov-report=term-missing --cov-fail-under=85"` to `[tool.pytest.ini_options]` (85% gives a 3% buffer for skipped database_query tests). Effort: S. Verification: `pytest tests/ --ignore=tests/test_database_query -q` passes and prints coverage summary >=85%.

5. **asyncio_default_fixture_loop_scope unset deprecation warning** -- `pyproject.toml`. Every pytest run emits `PytestDeprecationWarning: asyncio_default_fixture_loop_scope is unset` -- visible in CI logs and signals maintenance lag on pytest-asyncio API changes. Fix: add `asyncio_default_fixture_loop_scope = "function"` to `[tool.pytest.ini_options]`. Effort: S. Verification: `pytest -x -q 2>&1 | grep -c "PytestDeprecationWarning"` returns 0.

---

## P1 Issues (next cycle, sub-2-hour items)

1. **"Production-ready" assertion in README opener** -- `README.md` line 7. "Production-ready" is an unsupported claim. Replace with the specific proof already on hand: "MCP server framework with built-in TTL caching (P50: 0.007ms hit), per-provider circuit breakers, and OpenTelemetry tracing." Effort: S. Verification: `grep -i "production-ready" README.md` returns empty.

2. **Static coverage badge** -- `README.md`. The `img.shields.io/badge/coverage-88%25` badge is hardcoded and will never update. Fix: enable Codecov on the repo (free for OSS), add `codecov/codecov-action` to CI, replace badge with live Codecov badge. Effort: M. Verification: badge URL contains codecov.io.

3. **ADR-0004: A2A adapter design** -- `docs/adr/`. The `A2AAdapter` is the repo's most novel feature but has no ADR. Missing decisions: which A2A spec version is targeted, how MCP tool metadata maps to A2A AgentCard capabilities, whether task state surviving restarts is in scope. Effort: S. Verification: `ls docs/adr/` shows ADR-0004.

4. **Evals cover only 1 of 9 servers** -- `evals/`. CacheLayer TTL correctness, rate limiter boundary behavior, and A2A adapter task routing have no eval coverage beyond unit tests. Add 5-8 deterministic cases for CacheLayer (TTL expiry, L1-miss/L2-hit path, key collision) and 3-5 for A2AAdapter (task completion, status retrieval, unknown tool). Effort: M. Verification: `python evals/run_evals.py` shows >20 cases.

5. **pyright non-blocking** -- `.github/workflows/ci.yml`. Commit `e8d64ab` disabled pyright with `continue-on-error: true`. For an MCP framework claiming production quality, type safety is table stakes. Fix: run `pyright mcp_toolkit/` locally, resolve errors, re-enable as blocking. Effort: M (depends on error count). Verification: `pyright mcp_toolkit/` exits 0.

---

## Architecture Recommendations

1. **ADR-0004 -- A2A adapter scope and protocol compliance**: The `A2AAdapter` bridges MCP to Google's A2A task protocol and is the repo's most differentiated feature, but there is no documented decision record. An ADR should capture: which A2A spec version is targeted, how MCP tool metadata maps to A2A AgentCard capabilities, how task state survives server restarts (currently it does not -- in-process dict), and whether the current implementation is complete or experimental. A reviewer will ask about this in any phone screen about this repo.

2. **Eval suite for CacheLayer correctness**: The L1/L2 cache is the most-used framework component. Its correctness proofs are unit tests only. A small golden-set eval (10-15 cases) testing TTL boundary behavior, L1/L2 hit paths, and rate limiter threshold edge cases would close the "tests pass but system behavior is unverified" gap and demonstrate eval discipline beyond the already-wired multi_llm routing tests.

---

## Hiring Decision Simulation

Would I advance this candidate? **Yes-with-reservations.**

The repo demonstrates genuine production thinking: per-provider circuit breakers with documented thresholds, a two-tier cache with a clear upgrade path, and an A2A adapter that shows awareness of where the MCP ecosystem is heading. The ADRs are the strongest signal -- they describe actual tradeoffs, not just what was built. The PyPI publication and clean Quick Start lower the bar for a reviewer to verify the claims. What holds this back from a clean "Yes": the stale test count (412 vs 383) signals a repo that is not regularly verified against its own claims; the eval suite covers 1 of 9 servers and has no CI gate; and pyright running non-blocking suggests type-safety is aspirational, not enforced. A senior AI engineer at a serious shop would notice all three in the first 15 minutes. Fix P0-1 through P0-5 and this repo clears the phone-screen bar cleanly.

---

## Re-review notes

*(To be filled after Stage 3 FIX)*
