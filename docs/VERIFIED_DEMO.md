# Verified local cache demonstration

Captured 2026-09-26 from base commit `dcf1da1485b90b38b345cf9122a549404eac128a` plus this working-tree patch. The new `examples/verified_cache.py` is the capture source.

## Reproduce

Use the supported source install from the README, then:

```bash
python examples/verified_cache.py
```

The example registers a real cached tool on `EnhancedMCP` and dispatches twice using `MCPTestClient`, which calls the MCP SDK in-process. The handler executes once. Actual `TelemetryProvider` in-memory records contain `cache_hit: false` then `cache_hit: true`.

This does not demonstrate network transport, external OTLP export, authentication, remote services or paid model calls. The greeting is a deterministic local example. The duration values in the [captured JSON](assets/cache-run.json) are one run, not a benchmark.

## Artwork provenance

- [Receipt source](assets/cache-receipt.html): editorial layout of actual results from the captured JSON, paired with an excerpt of the runnable example.
- [Receipt PNG](assets/cache-receipt.png): unaltered Chrome screenshot of that local HTML at 1280 by 640. It is an editorial receipt, not an application or Jaeger screenshot.
- Capture command: `agent-browser --session hero-mcp-audit screenshot docs/assets/cache-receipt.png` after navigating to the local HTML and setting the viewport to 1280 by 640.
- The HTML reflows at 375px; the PNG cannot. The README repeats the essential result and reproduction link in text.

## Walkthrough correctness

The separate Streamlit RAG walkthrough is a plain Python example, not MCP dispatch. The default query returns fixed ranked sources and template text. Changing the chunk slider now changes the pipeline result count. Empty retrieval produces an explicit no-answer result. Configured retrieval/synthesis failures now produce an explicit error rather than silently replacing live output with fixtures; database connections close on fetch failure.

These paths were exercised in Chrome: initial render, query submission, changing the chunk slider from four to two, resulting source count, mobile rendering. The static HTML preview also supports keyboard form submission and moves focus to the resulting region. Neither page had horizontal document overflow at a 375px viewport.

## Validation

An existing Python environment was reused without installing packages. `PYTHONPATH` pointed at this checkout and the resolved `mcp_toolkit.__file__` was verified before execution. A fresh installation was not performed.

- `python -m pytest tests/ -q`: **603 passed, 2 skipped**, 28 warnings.
- `python -m ruff check examples/verified_cache.py examples/agentic_rag/app.py tests/test_demo_walkthrough.py`: passed.
- `python -m ruff format --check` on those same files: passed.
- `git diff --check`: passed.

Configured APIs, real semantic retrieval, external OTLP export and anonymous hosted availability were not verified. The deterministic embedding is not a semantic-search integration. No credentials were read and no paid requests were made.
