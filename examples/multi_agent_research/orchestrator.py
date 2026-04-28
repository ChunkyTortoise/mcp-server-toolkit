"""Multi-agent research orchestrator.

Demonstrates MCP + A2A coexistence:
  - Uses multi_llm toolkit server for parallel second opinions
  - Uses web_scraping toolkit server for live sources
  - Bridges final answer back via A2AAdapter for downstream A2A consumers

Run:
    python examples/multi_agent_research/orchestrator.py "What is retrieval-augmented generation?"

Architecture:
    User query
        │
        ├─► WebScraper (MCP) ──► raw sources
        ├─► MultiLLM/cheap (MCP) ──► quick summary
        └─► MultiLLM/best (MCP) ──► deep synthesis
              │
              └─► Merge + cite ──► A2AAdapter ──► JSON response
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

from mcp.types import TextContent

from mcp_toolkit import EnhancedMCP
from mcp_toolkit.framework.a2a_adapter import A2AAdapter


def _extract_text(result: object) -> str:
    """Extract plain text from an MCP tool call result."""
    if isinstance(result, str):
        return result
    if isinstance(result, tuple) and result:
        result = result[0]
    if isinstance(result, list) and result:
        item = result[0]
        if isinstance(item, TextContent):
            return item.text
        return str(item)
    return str(result)

# ---------------------------------------------------------------------------
# Lightweight mock clients for standalone demo (no real API keys needed)
# ---------------------------------------------------------------------------

class _MockWebClient:
    async def search(self, query: str, max_results: int = 3) -> list[dict]:
        return [
            {"title": f"Source {i+1}: {query}", "url": f"https://example.com/{i+1}", "snippet": f"Relevant excerpt {i+1} about {query}."}
            for i in range(max_results)
        ]


class _MockLLMClient:
    def __init__(self, model_tier: str):
        self._tier = model_tier

    async def complete(self, prompt: str) -> str:
        return f"[{self._tier} synthesis of: {prompt[:60]}...]"


# ---------------------------------------------------------------------------
# MCP servers
# ---------------------------------------------------------------------------

def _build_web_server() -> EnhancedMCP:
    mcp = EnhancedMCP("research-web")
    client = _MockWebClient()

    @mcp.tool()
    async def web_search(query: str, max_results: int = 3) -> str:
        """Search the web and return ranked results."""
        results = await client.search(query, max_results)
        lines = [f"[{r['title']}]({r['url']})\n{r['snippet']}" for r in results]
        return "\n\n".join(lines)

    return mcp


def _build_llm_server() -> EnhancedMCP:
    mcp = EnhancedMCP("research-llm")
    cheap = _MockLLMClient("cheap")
    best = _MockLLMClient("best")

    @mcp.tool()
    async def quick_summary(text: str) -> str:
        """Generate a fast, concise summary using a cheap model."""
        return await cheap.complete(text)

    @mcp.tool()
    async def deep_synthesis(sources: str, query: str) -> str:
        """Generate a detailed, cited answer using the best model."""
        prompt = f"Query: {query}\n\nSources:\n{sources}"
        return await best.complete(prompt)

    return mcp


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

@dataclass
class ResearchResult:
    query: str
    sources: list[str]
    summary: str
    deep_answer: str
    task_id: str


async def research(query: str) -> ResearchResult:
    """Run multi-agent research pipeline for a query."""
    web_mcp = _build_web_server()
    llm_mcp = _build_llm_server()

    # Step 1: parallel — web search + quick summary
    web_task = web_mcp.call_tool("web_search", {"query": query, "max_results": 4})
    summary_task = llm_mcp.call_tool("quick_summary", {"text": query})
    raw_sources, quick = await asyncio.gather(web_task, summary_task)

    source_text = _extract_text(raw_sources)
    quick_text = _extract_text(quick)

    # Step 2: sequential — deep synthesis with sources
    deep = await llm_mcp.call_tool(
        "deep_synthesis", {"sources": source_text, "query": query}
    )
    deep_text = _extract_text(deep)

    # Step 3: expose as A2A task for downstream consumers
    adapter = A2AAdapter(llm_mcp, base_url="http://localhost:9000", description="Research orchestrator")
    task_id = f"research-{hash(query) & 0xFFFFFF:06x}"
    # Store final result in adapter task registry
    from mcp_toolkit.framework.a2a_adapter import A2ATaskStatus
    final_status = A2ATaskStatus(
        task_id=task_id,
        status="completed",
        message=deep_text,
        result={"query": query, "answer": deep_text, "sources": source_text},
    )
    adapter._tasks[task_id] = final_status

    return ResearchResult(
        query=query,
        sources=source_text.split("\n\n"),
        summary=quick_text,
        deep_answer=deep_text,
        task_id=task_id,
    )


async def main(query: str) -> None:
    print(f"\n Research query: {query!r}\n")

    result = await research(query)

    print("── Sources ──────────────────────────────────────")
    for i, src in enumerate(result.sources[:3], 1):
        first_line = src.split("\n")[0] if src else ""
        print(f"  [{i}] {first_line}")

    print("\n── Quick summary ────────────────────────────────")
    print(f"  {result.summary}")

    print("\n── Deep synthesis ───────────────────────────────")
    print(f"  {result.deep_answer}")

    print(f"\n── A2A task ID: {result.task_id} ──────────────")
    print("  (Downstream A2A consumers can poll /tasks/{task_id})")


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) or "What is retrieval-augmented generation?"
    asyncio.run(main(query))
