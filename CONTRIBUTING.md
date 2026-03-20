# Contributing to mcp-server-toolkit

## Prerequisites

- Python 3.10+
- [hatch](https://hatch.pypa.io/) (`pip install hatch`)
- Redis (optional — only needed for caching/rate-limiting tests)

## Setup

```bash
git clone https://github.com/ChunkyTortoise/mcp-server-toolkit
cd mcp-server-toolkit
pip install -e ".[dev]"
```

## Running Tests

```bash
# Full suite
pytest tests/ -v --cov=mcp_toolkit --cov-report=term-missing --cov-fail-under=90

# Quick smoke test
pytest tests/ -q --tb=short

# Single server tests
pytest tests/servers/test_filesystem.py -v
```

## Lint

```bash
ruff check .
ruff format --check .
```

Auto-fix:
```bash
ruff check --fix .
ruff format .
```

## Adding a New Server

1. Create `mcp_toolkit/servers/your_server.py`
2. Subclass `EnhancedMCP` and register tools with `@self.tool()`
3. Add tests in `tests/servers/test_your_server.py` — aim for ≥80% coverage on the new file
4. Export from `mcp_toolkit/servers/__init__.py`
5. Add a `<details>` block to the "Pre-built Servers" section of `README.md`
6. Update `CHANGELOG.md` under `[Unreleased]`

## PR Process

1. Fork the repo and create a branch: `git checkout -b feat/your-feature`
2. Write tests first (TDD)
3. Run the full test suite — all tests must pass, coverage must stay ≥90%
4. Run lint — zero ruff errors
5. Open a PR with a clear description of the change and why

## Release Process (maintainers only)

```bash
hatch version patch   # or minor / major
hatch build
hatch publish
```

Update `CHANGELOG.md` before publishing.
