"""Tests for web scraping MCP server."""

from unittest.mock import AsyncMock

import pytest

from mcp_toolkit.framework.testing import MCPTestClient
from mcp_toolkit.servers.web_scraping import server as ws_server
from mcp_toolkit.servers.web_scraping.extractor import MockExtractorLLM
from mcp_toolkit.servers.web_scraping.scraper import ScrapedPage, WebScraper


@pytest.fixture
def mock_scraper():
    """Create a mock scraper that returns fake pages."""
    scraper = AsyncMock(spec=WebScraper)
    scraper.scrape = AsyncMock(
        return_value=ScrapedPage(
            url="https://example.com",
            status_code=200,
            html="<html><body><h1>Test</h1><p>Content here</p></body></html>",
            text="Test\nContent here",
            title="Test Page",
            links=["https://example.com/about"],
            meta={"description": "A test page"},
        )
    )
    return scraper


@pytest.fixture
def configured_server(mock_scraper):
    """Configure server with mocked scraper."""
    llm = MockExtractorLLM()
    llm.add_response("product", '{"products": [{"name": "Widget", "price": 9.99}]}')
    ws_server.configure(llm=llm, requests_per_second=100, respect_robots=False)
    # Patch the global scraper
    original = ws_server._scraper
    ws_server._scraper = mock_scraper
    yield MCPTestClient(ws_server.mcp)
    ws_server._scraper = original


class TestScrapeUrlTool:
    async def test_scrape_returns_content(self, configured_server):
        result = await configured_server.call_tool("scrape_url", {"url": "https://example.com"})
        assert "Test Page" in result
        assert "Content" in result

    async def test_scrape_includes_url(self, configured_server):
        result = await configured_server.call_tool("scrape_url", {"url": "https://example.com"})
        assert "example.com" in result

    async def test_scrape_error_handling(self, mock_scraper):
        mock_scraper.scrape.return_value = ScrapedPage(
            url="https://bad.com",
            status_code=500,
            html="",
            text="",
            error="Server Error",
        )
        ws_server._scraper = mock_scraper
        client = MCPTestClient(ws_server.mcp)
        result = await client.call_tool("scrape_url", {"url": "https://bad.com"})
        assert "Error" in result


class TestExtractDataTool:
    async def test_extract_returns_json(self, configured_server):
        result = await configured_server.call_tool(
            "extract_data",
            {"url": "https://example.com", "description": "product names and prices"},
        )
        assert "Extracted from" in result or "extracted" in result.lower()


class TestToolListing:
    async def test_has_expected_tools(self, configured_server):
        tools = await configured_server.list_tools()
        names = {t["name"] for t in tools}
        assert "scrape_url" in names
        assert "extract_data" in names
