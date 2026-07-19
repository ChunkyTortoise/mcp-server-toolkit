# MCP Hireability Scorecard — 2026-07-19

**Lane:** Full-stack AI eng  
**Method:** Parallel specialist agents (hiring-manager, architect, security, claims honesty)  
**Baseline commit before remediation:** `3659371` (implementation plan)  
**Design:** `docs/superpowers/specs/2026-07-19-mcp-hireability-overhaul-design.md`

## Dimension scores (pre-remediation)

| Dimension | Score | Notes |
|---|---|---|
| Hiring-manager / Demo | 5/10 | No hosted URL; local Streamlit + static Jaeger only |
| Architect / Product honesty | 6/10 | Flagship RAG example does not import `mcp_toolkit` |
| Security / gates | 5/10 | Substrate auditor local WIP; gates via blanket pytest only |
| Claims honesty | 4/10 | Coverage % stale; auditor claimed in CI but untracked |
| Eval / CI rigor | 7/10 | CI matrix + nightly workflow present; nightly health TBD |
| **Composite (approx)** | **~27/50** | Kill gates open → not interview-ready for lane C |

Target after Waves 1–3: **~42/50+** with Demo kill-gates cleared.

## Kill gates

| Gate | Owner | Result | Evidence |
|---|---|---|---|
| No clickable demo | HM / Demo UX | **FAIL** | `README.md` Demo table — local only; Render Jaeger undeployed |
| Claims ahead of git | HM / Claims | **FAIL** | `?? mcp_toolkit/security/`; README Hiring Evidence cites auditor CI |
| production-ready without proof | HM | **FAIL** | `pyproject.toml` description vs Beta classifier; no deploy |
| README ≠ measured reality | Claims | **FAIL** | README 82.87% cov; measured ~79–80% tracked; auditor not in git |
| Auditor documented but uncommitted | Security | **FAIL** | `git ls-files mcp_toolkit/security` empty |
| Dead / misleading examples | Architect | **FAIL** | `examples/agentic_rag/app.py` — no `mcp_toolkit` imports; README "4 tool calls" |

## Ranked backlog (remediation)

### P0 (must ship this cycle)

1. **Host dual-mode agentic RAG + GIF** — Deploy stranger-reachable demo; pin URL + GIF in README. Fix sketch: `examples/agentic_rag/` pipeline + Render blueprint + assets.
2. **Commit substrate auditor + wire CI** — Land `mcp_toolkit/security/` + `tests/security/`; add explicit CI step or rely on pytest once tracked; keep README claim only after merge.
3. **Scrub production-ready + align metrics** — Rewrite `pyproject.toml` description; refresh coverage % and test count from measured runs; align Makefile/CONTRIBUTING floors to CI 80%.
4. **Honest RAG ↔ toolkit wiring** — Register embed/retrieve/synthesize via `EnhancedMCP` tools *or* scrub MCP/"4 tool calls" claims; label demo vs live modes clearly.

### P1 (ship if they move full-stack signal)

5. **Fix `.claude/CLAUDE.md` PyPI 0.3.0 install claim** — Match README source-install-first.
6. **Coverage floor triangulation** — Makefile/CONTRIBUTING 88%/90% → 80% (CI SoT).
7. **Rate-limit public demo** — Sliding-window cap even in demo mode.
8. **ADR-0005 RedisSlidingWindow drift** — Doc note or defer (out of Wave 1 scope unless quick).

### P2 (defer)

9. Email/calendar README stubs; multi_agent_research using pre-builts; adversarial "30 cases validated" wording nuance.
10. PyPI publish 0.3.0 — owner-gated, out of cycle.

## Post-remediation (fill in Wave 3)

| Dimension | Score | Notes |
|---|---|---|
| Hiring-manager / Demo | _TBD_ | |
| Architect / Product honesty | _TBD_ | |
| Security / gates | _TBD_ | |
| Claims honesty | _TBD_ | |
| Eval / CI rigor | _TBD_ | |
| **Composite** | _TBD_ | |

Kill gates post-fix: _TBD_
