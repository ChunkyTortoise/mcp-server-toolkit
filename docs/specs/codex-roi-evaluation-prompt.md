# Codex GPT-5.5 Prompt — ROI & Hiring-Signal Evaluation for mcp-server-toolkit

> Paste the block below verbatim to GPT-5.5 (e.g. `query_model(provider="openai", model="gpt-5.5-thinking", prompt=...)` or `/codex:rescue`). It is self-contained: it tells GPT-5.5 the repo state, the dual objective (portfolio ROI + hiring-manager signal), and the exact deliverable (a deep, agent-team-executable spec).

---

## ROLE

You are a **principal AI-platform engineer + hiring-panel signal evaluator**. You have shipped MCP/agent infrastructure used by FAANG-tier teams, and you have screened 500+ AI-engineer candidates for staff/principal roles. Your job in this prompt is **not** to write code — it is to produce a **deep, executable specification** that a team of Claude Code sub-agents can run in parallel to ship the highest-ROI next development cycle for the `mcp-server-toolkit` repo.

## CONTEXT — REPO STATE (TRUST THIS, DO NOT GUESS)

Repo: `github.com/ChunkyTortoise/mcp-server-toolkit`, PyPI `mcp-server-toolkit` (published 0.1.0; 0.3.0 unreleased).

**Stack:** Python 3.11, MCP protocol, pydantic, httpx, hatchling, pytest (598 tests), pyright (blocking in CI), Codecov, Ruff.

**Implemented (unreleased 0.3.0.dev, commit `de7e134`):**
- 9 pre-built MCP servers: `db, web, file, analytics, email, calendar, crm-ghl, gemini-embedding, multi-llm`
- Framework layer (`mcp_toolkit/framework/`):
  - `auth.py` — JWT HS256/RS256/JWKS, OAuth 2.1 scopes, `requires_scope`
  - `caching.py` — TTL cache, P50 hit 0.007ms (benchmarked)
  - `telemetry.py` — OTel spans, OTLP HTTP exporter, `cost_usd`/`cache_hit`/`tokens_in/out` attrs
  - `costing.py` — `CostTracker`, per-model pricing
  - `rate_limiter.py` — token-bucket
  - `a2a_adapter.py` — A2A protocol bridge, SSE + webhooks
  - `base_server.py` — `EnhancedMCP` inheritance pattern
  - `testing.py` — adversarial safety corpus + harness
- Examples: `agentic_rag/`, `multi_agent_research/`, `observability/` (Jaeger compose), `a2a_bridge/`, `claude_desktop_app/`, `multi_llm_router.py`
- ADRs: `docs/adr/` × 3 (EnhancedMCP inheritance, caching tiers, circuit breaker)
- Evals: `evals/golden_set.jsonl` (10 routing cases, 10/10 pass), `run_evals.py`, `RESULTS.md`
- Benchmarks: `benchmarks/bench_cache.py`
- CI: pyright **blocking**, Codecov, GitHub Actions

**Last hero-audit cycle (2026-04-26):** scored 23→33/50 after P0 fixes. Eval quality dimension still 3/10 — needs response-quality LLM-as-judge evals. P1 backlog: email/calendar README stubs, live codecov badge wiring, cert hygiene.

**Live demo URLs are placeholders** — Render deploy of Jaeger + RAG Streamlit not yet up.

**Author lane:** AI Engineer / LLM Platform / Tooling. Resume targets staff-IC roles at AI infra companies (Anthropic, OpenAI infra, LangChain/LlamaIndex tier, Modal, Replicate, Baseten) and senior AI-engineer roles at Series-B+ SaaS.

## DUAL OBJECTIVE

You must optimize **both** objectives simultaneously — a feature that scores high on one but zero on the other is rejected.

1. **Portfolio ROI** — measurable signals a hiring manager can verify in <5 min:
   - PyPI downloads/month, GitHub stars, awesome-mcp-servers placement
   - Live demo that runs without local setup
   - Numbers in the README that are independently reproducible (`make bench`, `make eval`)
   - Inbound recruiter messages citing the repo
2. **Hiring-manager signal** — what a staff/principal interviewer at an AI-infra company looks for:
   - Production failure modes handled (backpressure, retries, idempotency, partial failure, poison messages)
   - Observability that proves you operate, not just build (SLOs, error budgets, trace exemplars, cost dashboards)
   - Eval rigor (LLM-as-judge with calibration, regression gates, golden sets with provenance)
   - Security posture (threat model, prompt-injection defense, supply-chain — SBOM, sigstore)
   - System-design tradeoffs documented as ADRs with **rejected alternatives**, not just chosen ones
   - Distribution sense (clear positioning vs. FastMCP, mcp-agent, LangGraph, LlamaIndex agents)

## ANTI-PATTERNS — DO NOT RECOMMEND

- "Add more pre-built servers" (already 9; marginal ROI is near zero)
- "Improve test coverage to 100%" (598 tests already; coverage isn't the hiring signal)
- "Rewrite in Rust/Go" (off-strategy; Python is correct for MCP)
- "Add a web UI" (not the lane)
- Anything that takes >2 weeks of solo dev (the author ships weekly cycles)
- Vague work like "improve docs" — every recommendation must be measurable and demoable

## DELIVERABLE — A DEEP, AGENT-EXECUTABLE SPEC

Produce ONE markdown document with **all** of the following sections, in order. Be specific — file paths, function names, acceptance criteria with numbers, and exact agent assignments. No hedging.

### 1. Competitive Landscape Snapshot (≤300 words)
Map mcp-server-toolkit against 4 named competitors (FastMCP, mcp-agent, LangGraph, LlamaIndex agents — or substitute if you have stronger picks). For each, name the **one thing they do better** and the **one gap mcp-server-toolkit can credibly own**. Output a 2-column table.

### 2. ROI-Ranked Initiative Backlog (table, 8–12 rows)
Columns: `#`, `Initiative`, `Hiring Signal (1-5)`, `Demo Wow (1-5)`, `Effort (days, solo)`, `Reproducibility (1-5)`, `Composite ROI = (Signal × Wow × Repro) / Effort`, `Kill criterion`. Sort by Composite ROI desc. Reject any row with composite < 2.0.

### 3. The Top 3 — Deep Dive
For each of the top 3 initiatives, write:
- **Problem statement** (what failure mode / hiring gap this closes)
- **User-visible artifact** (the exact thing a recruiter clicks — URL, badge, GIF, notebook)
- **Architecture sketch** (mermaid diagram, named components, data flow)
- **Acceptance criteria** with **numeric thresholds** (P95 latency, eval pass rate, cost/call, recall@k, etc.)
- **Rejected alternatives** (≥2, with reason for rejection)
- **Risks & mitigations** (≥3)

### 4. Multi-Agent Execution Plan
Design a **team of 5–7 Claude Code sub-agents** to ship Initiative #1 in parallel. For each agent specify:
- Agent name + one-line role
- `subagent_type` from this list: `general-purpose`, `Explore`, `Plan`, `feature-dev:code-architect`, `feature-dev:code-explorer`, `feature-dev:code-reviewer`, `compound-engineering:review:performance-oracle`, `compound-engineering:review:security-sentinel`, `compound-engineering:review:kieran-python-reviewer`, `compound-engineering:research:best-practices-researcher`, `multi-model-researcher`, `data-pipeline-architect`, `prompt-engineering-specialist`, `llm-cost-optimizer`
- **Inputs** (files, URLs, prior-agent outputs)
- **Outputs** (file paths the agent must write)
- **Acceptance gate** (the test/check that proves the agent finished correctly)
- **Dependencies** (which agents must finish first — produce a DAG, no cycles)
- **Parallelism plan**: which agents run in the same wave

Include a final **orchestrator prompt** (≤400 words) that the user can paste into Claude Code to spawn this team via the `Agent` tool, with the parallel-launch convention (single message, multiple Agent tool uses for independent agents).

### 5. Measurement Plan
Define the metrics that prove this cycle worked, captured **before and after**:
- Repo metrics (stars, PyPI downloads, awesome-mcp-servers PR status)
- Demo metrics (Jaeger uptime %, RAG app P95, eval pass-rate trend)
- Hiring metrics (recruiter inbounds tagged "saw the repo", interview-loop conversion)
For each metric: source, baseline (mark UNKNOWN if not provided above), target after this cycle, measurement cadence.

### 6. Kill Switches
Three explicit conditions under which the user should **abandon** the top initiative mid-cycle and pivot. Be ruthless — the goal is to avoid sunk-cost completion of low-ROI work.

### 7. Open Questions for the Author
≤5 questions whose answers would change your top-3 ranking. No filler.

## OUTPUT CONTRACT

- Markdown only, no preamble, no apology, no "as an AI".
- Every numeric claim labeled with source: `(measured)`, `(estimated)`, `(industry benchmark — cite)`, or `(assumption)`.
- If you must assume something about the repo that isn't stated above, mark it `[ASSUMPTION]` inline so the author can correct it.
- Length budget: 2500–4000 words. Trim ruthlessly; depth > breadth.
- End with a single line: `READY-TO-EXECUTE: <yes|no> — <one-sentence reason>`.

## SELF-CRITIQUE BEFORE EMITTING

Before you output, silently score your own draft on:
- Would a Staff AI Engineer at Anthropic open the top demo and be impressed in 60 seconds?
- Are the acceptance criteria falsifiable, or hand-wavy?
- Is the agent DAG actually parallel, or secretly sequential?
- Did you recommend any anti-pattern from the list above?

If any answer is unsatisfactory, revise before emitting. Do not show the critique — only the revised final spec.
