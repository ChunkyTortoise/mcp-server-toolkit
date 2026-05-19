# MCP Server Toolkit

## Stack
Python | MCP protocol | pydantic | httpx | hatchling (build) | PyPI

## Architecture
9 pre-built MCP servers: db, web, file, analytics, email, calendar, crm-ghl, gemini-embedding, multi-llm. PyPI-published library. Build with `hatch build && twine upload`. `examples/` dir shows usage per server.
- `mcp_toolkit/`: main package with 9 server modules
- `mcp_toolkit/framework/a2a_adapter.py`: A2A protocol bridge
- `examples/`: usage examples per server
- `tests/`: 600 tests
- `pyproject.toml`: hatchling build config

## Deploy
PyPI library (published: **0.1.0**): `pip install mcp-server-toolkit`. 0.3.0 is in development (unreleased) — do not reference `==0.3.0` until it is published. Submit to awesome-mcp-servers after updates.

## Test
```pytest tests/  # 600 tests```

## Key Env
PYPI_API_TOKEN (for publishing only)
