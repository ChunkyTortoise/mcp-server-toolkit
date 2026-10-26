"""Web Scraping MCP Server, agent-driven scraping with structured extraction."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from mcp_toolkit.framework.base_server import EnhancedMCP
from mcp_toolkit.servers.web_scraping.extractor import (
    DataExtractor,
    DefaultLLMProvider,
    LLMProvider,
)
from mcp_toolkit.servers.web_scraping.scraper import ScrapedPage, WebScraper

logger = logging.getLogger(__name__)

mcp = EnhancedMCP("web-scraping")

_scraper = WebScraper()
_extractor = DataExtractor()


def configure(
    llm: LLMProvider | None = None,
    requests_per_second: float = 1.0,
    respect_robots: bool = True,
) -> None:
    """Configure the web scraping server."""
    global _scraper, _extractor
    _scraper = WebScraper(
        requests_per_second=requests_per_second,
        respect_robots=respect_robots,
    )
    _extractor = DataExtractor(llm=llm or DefaultLLMProvider())


async def _scrape_page(url: str, css_selector: str | None = None) -> ScrapedPage:
    try:
        page = await _scraper.scrape(url, css_selector=css_selector)
    except Exception as exc:
        logger.warning("Scrape failed: %s", type(exc).__name__)
        raise ToolError("Unable to scrape page") from None
    if not page.is_success:
        logger.warning("Scrape refused or page unavailable")
        raise ToolError("Unable to scrape page")
    return page


@mcp.tool()
async def scrape_url(
    url: str,
    css_selector: str | None = None,
) -> str:
    """Scrape a web page and return its text content.

    Args:
        url: The URL to scrape.
        css_selector: Optional CSS selector to extract specific elements.

    Returns:
        The page text content, title, and metadata.
    """
    result = await _scrape_page(url, css_selector=css_selector)

    parts = [f"**Title:** {result.title}\n"] if result.title else []
    parts.append(f"**URL:** {result.url}\n")

    if result.meta:
        desc = result.meta.get("description", "")
        if desc:
            parts.append(f"**Description:** {desc}\n")

    parts.append(f"\n**Content:**\n{result.text[:10000]}")

    if len(result.text) > 10000:
        parts.append(f"\n\n*Content truncated. Total length: {len(result.text)} chars.*")

    if result.links:
        parts.append(f"\n\n**Links found:** {len(result.links)}")

    return "\n".join(parts)


@mcp.tool()
async def extract_data(
    url: str,
    description: str,
    schema: dict[str, Any] | None = None,
) -> str:
    """Scrape a URL and extract structured data using an LLM.

    Args:
        url: The URL to scrape.
        description: What data to extract (e.g., "product names and prices").
        schema: Optional JSON schema for the expected output format.

    Returns:
        Extracted data as formatted JSON.
    """
    page = await _scrape_page(url)

    if schema:
        result = await _extractor.extract_with_schema(page.text, schema, source_url=url)
    else:
        result = await _extractor.extract_freeform(page.text, description, source_url=url)

    if not result.success:
        return f"Extraction error: {result.error}"

    import json

    return f"**Extracted from:** {url}\n\n```json\n{json.dumps(result.data, indent=2)}\n```"


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
