# MCP Hireability Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a parallel specialist hireability audit, then ship dual-mode hosted agentic RAG + credibility hygiene so a full-stack AI eng hiring manager can click a live demo in under 60 seconds.

**Architecture:** Grok orchestrates five audit passes into one scored backlog; remediation ships in three waves (RAG demo → claims/CI hygiene → bounded eval/security). Demo defaults to deterministic fixtures; live LLM only when a server-side key is present.

**Tech Stack:** Python 3.10+, Streamlit, pytest, GitHub Actions, Render (or Streamlit Community Cloud), stdlib substrate auditor

**Design spec:** `docs/superpowers/specs/2026-07-19-mcp-hireability-overhaul-design.md`

---

## File map

| Path | Responsibility |
|---|---|
| `docs/superpowers/specs/2026-07-19-mcp-hireability-scorecard.md` | Merged agent audit scorecard + ranked backlog |
| `examples/agentic_rag/pipeline.py` | Testable dual-mode RAG pipeline (embed/retrieve/synthesize/rate limit) |
| `examples/agentic_rag/app.py` | Streamlit UI; mode labels; cold-start banner |
| `examples/agentic_rag/render.yaml` | Render web service blueprint for hosted demo |
| `examples/agentic_rag/requirements-demo.txt` | Minimal deps for hosted demo |
| `examples/agentic_rag/README.md` | Local + hosted runbook |
| `tests/examples/test_agentic_rag_pipeline.py` | Unit tests for demo/live mode detection and fixtures |
| `assets/agentic-rag-demo.gif` | Short walkthrough GIF (or frame sequence) |
| `mcp_toolkit/security/*` | Commit substrate auditor (if kept) |
| `tests/security/*` | Auditor tests + samples |
| `.github/workflows/ci.yml` | Optional substrate-auditor step |
| `README.md` | Hero demo link, GIF, honest metrics |
| `.claude/CLAUDE.md` | Scrub stale PyPI / test-count claims |
| `pyproject.toml` | Scrub "Production-ready" description |
| `CONTRIBUTING.md` / `Makefile` | Align coverage floor messaging with CI (80%) |
| `.gitignore` | Ignore `.superpowers/` brainstorm artifacts |

---

### Task 1: Parallel specialist audit → scorecard

**Files:**
- Create: `docs/superpowers/specs/2026-07-19-mcp-hireability-scorecard.md`

- [ ] **Step 1:** Run five passes in parallel (hiring-manager, architect, security, demo UX, claims honesty) against the design rubrics. Require fresh evidence paths.
- [ ] **Step 2:** Merge findings: kills → P0; dedupe mediums; cap to P0 + top full-stack P1s.
- [ ] **Step 3:** Write scorecard with dimension scores (/50 style), kill-gate table, ranked backlog.
- [ ] **Step 4:** Commit scorecard.

```bash
git add docs/superpowers/specs/2026-07-19-mcp-hireability-scorecard.md
git commit -m "$(cat <<'EOF'
docs: add hireability scorecard from specialist agent audit

EOF
)"
```

---

### Task 2: Extract testable dual-mode pipeline

**Files:**
- Create: `examples/agentic_rag/pipeline.py`
- Create: `tests/examples/test_agentic_rag_pipeline.py`
- Modify: `examples/agentic_rag/app.py`

- [ ] **Step 1: Write failing tests** for `detect_mode()`, demo retrieve, demo synthesize (no keys), rate-limit helper.

```python
# tests/examples/test_agentic_rag_pipeline.py
from examples.agentic_rag.pipeline import detect_mode, retrieve_chunks, synthesize, RateLimiter

def test_detect_mode_demo_by_default(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PGVECTOR_URL", raising=False)
    assert detect_mode() == "demo"

def test_demo_synthesize_never_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # ... assert answer contains citation markers and "Demo mode"
```

- [ ] **Step 2: Run tests — expect fail** (`uv run pytest tests/examples/test_agentic_rag_pipeline.py -q`).
- [ ] **Step 3: Implement `pipeline.py`** — move Chunk, DEMO_CHUNKS, embed/retrieve/synthesize/run_pipeline; add `detect_mode()`, `RateLimiter` (sliding window per IP/session), live fallback to demo on API errors.
- [ ] **Step 4: Thin `app.py`** to import pipeline; show mode badge; rate-limit before `run_pipeline`.
- [ ] **Step 5: Run tests — expect pass.** Commit.

---

### Task 3: Hosting blueprint + demo README

**Files:**
- Create: `examples/agentic_rag/render.yaml`
- Create: `examples/agentic_rag/requirements-demo.txt`
- Create: `examples/agentic_rag/README.md`

- [ ] **Step 1:** `requirements-demo.txt` with `streamlit`, `anthropic` (optional live).
- [ ] **Step 2:** `render.yaml` web service: `streamlit run examples/agentic_rag/app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true`.
- [ ] **Step 3:** README with local run, demo vs live env vars, deploy steps, cold-start note.
- [ ] **Step 4:** Deploy via Render MCP or document exact dashboard steps; capture public URL.
- [ ] **Step 5:** Commit blueprint + README; URL goes into root README in Task 5.

---

### Task 4: Walkthrough GIF

**Files:**
- Create: `assets/agentic-rag-demo.gif` (or `scripts/make_rag_demo_gif.py` + generated asset)
- Create: `assets/agentic-rag-demo-preview.html` only if GIF generation is blocked

- [ ] **Step 1:** Generate a short multi-frame GIF showing query → answer → sources (Pillow script acceptable).
- [ ] **Step 2:** Verify file size &lt; ~2MB.
- [ ] **Step 3:** Commit asset.

---

### Task 5: README hero surface

**Files:**
- Modify: `README.md` (top: Live demo URL + GIF; measured table test count; Hiring Evidence honesty)

- [ ] **Step 1:** Measure `pytest tests/ --collect-only -q` and update test count.
- [ ] **Step 2:** Add Demo section above Measured results with URL + GIF + one-line dual-mode note.
- [ ] **Step 3:** Demote observability to secondary in Demo table.
- [ ] **Step 4:** Commit.

---

### Task 6: Wave 2 — substrate auditor + claims hygiene

**Files:**
- Add: `mcp_toolkit/security/`, `tests/security/`
- Modify: `.github/workflows/ci.yml`, `README.md`, `pyproject.toml`, `.claude/CLAUDE.md`, `CONTRIBUTING.md`, `Makefile`, `.gitignore`

- [ ] **Step 1:** Run `pytest tests/security/ -q` — fix until green.
- [ ] **Step 2:** Add CI step: `python -m mcp_toolkit.security.substrate_auditor --help` + pytest security tests (or dedicated CLI on samples).
- [ ] **Step 3:** Align coverage messaging: CI stays 80%; Makefile/CONTRIBUTING say 80% (or document local stricter 88% as optional). Prefer **align all to 80%** to match CI.
- [ ] **Step 4:** Scrub `Production-ready` from `pyproject.toml` description.
- [ ] **Step 5:** Fix `.claude/CLAUDE.md` PyPI/`600 tests` claims.
- [ ] **Step 6:** Add `.superpowers/` to `.gitignore`.
- [ ] **Step 7:** Verify nightly workflow file is coherent; trigger `workflow_dispatch` if secrets available, else note status in scorecard.
- [ ] **Step 8:** Commit Wave 2.

---

### Task 7: Wave 3 — bounded eval/security depth + rescore

**Files:**
- Modify or create: small RAG-related eval case if cheap (`evals/` or `tests/test_evals/`)
- Modify: `docs/superpowers/specs/2026-07-19-mcp-hireability-scorecard.md` (post-fix scores)

- [ ] **Step 1:** Add one deterministic eval/test that agentic RAG demo mode returns cited answer without keys.
- [ ] **Step 2:** Confirm substrate auditor runs in CI config.
- [ ] **Step 3:** Re-run scorecard dimensions; mark kill-gates cleared/failed.
- [ ] **Step 4:** Full `uv run pytest tests/ -q --cov=mcp_toolkit --cov-fail-under=80`.
- [ ] **Step 5:** Final commit.

---

## Verification checklist (Definition of Done)

- [ ] Hosted RAG URL works in demo mode without visitor keys
- [ ] GIF/video linked above the fold
- [ ] Scorecard shows Demo kill-gates addressed; overall ~42/50+ target documented
- [ ] CI config includes auditor + coverage gate; local pytest green
- [ ] No false PyPI `0.3.0` install claim; no "Production-ready" in package description
- [ ] `.superpowers/` gitignored

## Out of scope (do not do)

- PyPI publish play (owner-gated separately)
- New MCP servers / satellite absorbs
- Hosted Jaeger as primary showcase
- Reordering global hero pin list
