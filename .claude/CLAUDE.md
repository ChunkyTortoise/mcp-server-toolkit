# MCP Server Toolkit

## Mission
Standing mission + task prompts live in `.claude/CLAUDE.local.md` (gitignored, private — never
commit it or copy its contents into tracked files). HARD RULES: every public number goes
through docs/claims.yaml + scripts/check_claims.py (never invent/round one); keep
"Methodology & limits" honest (label mock/synthetic/unverified as such); gates green (pytest w/
coverage floor, ruff pinned set, pyright, evals/run_evals.py); CHANGELOG for user-visible
changes; ADR for tradeoff decisions; PR-sized scope. Do not publish/deploy anything without
owner approval.

## Stack
Python | MCP protocol (mcp 2.x, >=2.3,<3) | pydantic | httpx | hatchling (build) | PyPI

## Architecture
9 pre-built MCP servers: db, web, file, analytics, email, calendar, crm-ghl, gemini-embedding, multi-llm. Build with `hatch build`; publish runs from a version tag via `.github/workflows/publish.yml` (PyPI Trusted Publishing, OIDC). `examples/` dir shows usage per server.
- `mcp_toolkit/`: main package with 9 server modules
- `mcp_toolkit/framework/a2a_adapter.py`: A2A protocol bridge
- `examples/`: usage examples per server
- `tests/`: test suite (run `pytest --collect-only -q` for the current count)
- `pyproject.toml`: hatchling build config

## Deploy
Install from source: `pip install -e ".[dev]"`. Repo version 0.4.0 (tag v0.4.0 pushed); PyPI
still serves the stale 0.1.0 preview — publishing 0.4.0 is an owner gate. Release checklist and
post-publish docs flip: docs/RELEASING.md. After publish: GitHub release object + MCP registry /
awesome-mcp listing. Submit to awesome-mcp-servers after updates.

## Test
```pytest tests/```
Also: `python evals/run_evals.py`; claims gate `python scripts/check_claims.py --check`.
Test count: run `pytest --collect-only -q` (README Results table holds the dated figure; update
both together when it changes).

## Key Env
None for publishing: PyPI trusted publishing (OIDC) via publish.yml, release environment
