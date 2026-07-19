# MCP Server Toolkit

## Stack
Python | MCP protocol | pydantic | httpx | hatchling (build) | PyPI

## Architecture
9 pre-built MCP servers: db, web, file, analytics, email, calendar, crm-ghl, gemini-embedding, multi-llm. Source install / editable for development; PyPI may lag. Build with `hatch build && twine upload`. `examples/` dir shows usage per server.
- `mcp_toolkit/`: main package with 9 server modules
- `mcp_toolkit/framework/a2a_adapter.py`: A2A protocol bridge
- `examples/`: usage examples per server
- `tests/`: run `pytest --collect-only -q` for current count
- `pyproject.toml`: hatchling build config

## Deploy
Install from source: `pip install -e ".[dev]"` (or `uv sync`). PyPI may lag behind main; do not assume `pip install mcp-server-toolkit==0.3.0` is current. Submit to awesome-mcp-servers after updates.

## Test
```pytest tests/  # run pytest --collect-only -q for count```

## Key Env
PYPI_API_TOKEN (for publishing only)
