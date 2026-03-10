# MCP Server Toolkit

## Stack
Python | MCP protocol | pydantic | httpx | hatchling (build) | PyPI

## Architecture
6 pre-built MCP servers: db, web, file, analytics, email, calendar. PyPI-published library. Build with `hatch build && twine upload`. `examples/` dir shows usage per server.
- `mcp_server_toolkit/` — main package with 6 server modules
- `examples/` — usage examples per server
- `tests/` — 233 tests
- `pyproject.toml` — hatchling build config

## Deploy
PyPI library — `pip install mcp-server-toolkit==0.1.0`. Submit to awesome-mcp-servers after updates.

## Test
```pytest tests/  # 233 tests```

## Key Env
PYPI_API_TOKEN (for publishing only)
