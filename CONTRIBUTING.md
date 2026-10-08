# Contributing to mcp-server-toolkit

## Prerequisites

- Python 3.10+
- Redis (optional, for real Redis integration)

## Setup

```bash
git clone https://github.com/ChunkyTortoise/mcp-server-toolkit
cd mcp-server-toolkit
pip install -e ".[dev]"
```

## Running Tests

```bash
# Suite with the current CI coverage floor
python -m pytest tests/ -x -q --tb=short --cov=mcp_toolkit --cov-report=term-missing --cov-fail-under=80

# Quick smoke test
python -m pytest tests/ -q --tb=short

# Single server tests
python -m pytest tests/test_file_processing/test_server.py -v
```

The required coverage floor is 80%, matching [CI](.github/workflows/ci.yml). `make test` retains an optional 88% target that the suite does not currently meet; use the command above to reproduce the CI requirement. Postgres integration tests skip unless `INTEGRATION=1` and `DATABASE_URL` are set. A passing default run does not verify external services.

## Lint

```bash
ruff check mcp_toolkit tests
pyright --pythonversion 3.10 mcp_toolkit
```

CI installs `pyright` separately from the development extras. Formatting can be checked with `ruff format --check mcp_toolkit tests`.

Auto-fix:
```bash
ruff check --fix .
ruff format .
```

## Adding a New Server

1. Create `mcp_toolkit/servers/your_server/` with `__init__.py` and `server.py`, following [file_processing](mcp_toolkit/servers/file_processing/).
2. Register tools on an `EnhancedMCP` instance with `@mcp.tool()`, and provide a `main()` entry point, following the existing server.
3. Add tests in `tests/test_your_server/`, including a successful tool call and rejected inputs.
4. Add a CLI entry point under `[project.scripts]` in `pyproject.toml` if the server is executable.
5. Document setup and usage in [examples/README.md](examples/README.md), and update the server inventory in `README.md` when it changes.
6. Update `CHANGELOG.md` under `[Unreleased]`

## PR Process

1. Fork the repo and create a branch: `git checkout -b feat/your-feature`
2. Write tests first (TDD)
3. Run the suite with the CI coverage floor above. All executed tests must pass; report skipped integration tests separately.
4. Run lint — zero ruff errors
5. Open a PR with a clear description of the change and why

## Release Process (maintainers only)

Release tooling uses [hatch](https://hatch.pypa.io/); it is not needed for the development test route above.

```bash
hatch version patch   # or minor / major
hatch build
hatch publish
```

Update `CHANGELOG.md` before publishing.
