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

## Post-remediation (Wave 3 — after Waves 1–2)

| Dimension | Score | Notes |
|---|---|---|
| Hiring-manager / Demo | 8/10 | GIF + static preview + Streamlit dual-mode; Render URL still pending workspace select |
| Architect / Product honesty | 8/10 | EnhancedMCP tools wired (`embed_query_tool`, `retrieve_chunks_tool`, `synthesize_tool`) |
| Security / gates | 8/10 | Substrate auditor committed + CI fixtures in `tests/security/` |
| Claims honesty | 8/10 | Metrics refreshed; production-ready scrubbed; Makefile/CONTRIBUTING floors aligned to CI 80% |
| Eval / CI rigor | 8/10 | CI auditor step + full pytest suite green with 80% cov gate |
| **Composite** | **~40/50** | Up from ~27/50; interview-ready for lane C pending hosted demo URL |

### Kill gates post-fix

| Gate | Result | Evidence |
|---|---|---|
| No clickable demo | **PARTIAL** | GIF + static preview in README; Render blueprint committed; live URL not deployed yet |
| Claims ahead of git | **PASS** | `mcp_toolkit/security/` tracked; README claims match git |
| production-ready without proof | **PASS** | `pyproject.toml` description scrubbed; Beta classifier honest |
| README ≠ measured reality | **PASS** | Coverage % and test counts refreshed from measured runs |
| Auditor documented but uncommitted | **PASS** | `mcp_toolkit/security/` + `tests/security/` in git; CI step wired |
| Dead / misleading examples | **PASS** | `examples/agentic_rag/` imports `EnhancedMCP`; demo vs live modes labeled |

### Residual P1

1. **Select Render workspace** — choose workspace in Render dashboard for `examples/agentic_rag/render.yaml` deploy.
2. **Create web service** — provision Streamlit web service from blueprint.
3. **Push branch for auto-deploy** — push `chore/hireability-punch-list` (or merge to main) so Render picks up the blueprint and pins a live URL in README.
