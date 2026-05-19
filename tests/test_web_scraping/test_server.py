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

    async def test_scrape_includes_title(self, configured_server):
        result = await configured_server.call_tool("scrape_url", {"url": "https://example.com"})
        assert "**Title:**" in result

    async def test_scrape_includes_description_when_present(self, configured_server):
        result = await configured_server.call_tool("scrape_url", {"url": "https://example.com"})
        assert "A test page" in result

    async def test_scrape_shows_link_count(self, configured_server):
        result = await configured_server.call_tool("scrape_url", {"url": "https://example.com"})
        assert "Links found" in result

    async def test_scrape_no_title_still_returns_content(self, mock_scraper):
        mock_scraper.scrape.return_value = ScrapedPage(
            url="https://example.com",
            status_code=200,
            html="<html><body>No title</body></html>",
            text="No title content",
            title="",
            links=[],
            meta={},
        )
        ws_server._scraper = mock_scraper
        client = MCPTestClient(ws_server.mcp)
        result = await client.call_tool("scrape_url", {"url": "https://example.com"})
        assert "No title content" in result
        assert "**Title:**" not in result

    async def test_scrape_truncation_note_for_long_content(self, mock_scraper):
        mock_scraper.scrape.return_value = ScrapedPage(
            url="https://example.com",
            status_code=200,
            html="<html><body>" + "x" * 15000 + "</body></html>",
            text="x" * 15000,
            title="Long Page",
            links=[],
            meta={},
        )
        ws_server._scraper = mock_scraper
        client = MCPTestClient(ws_server.mcp)
        result = await client.call_tool("scrape_url", {"url": "https://example.com"})
        assert "truncated" in result.lower()
        assert "15000" in result

    async def test_scrape_zero_status_error(self, mock_scraper):
        mock_scraper.scrape.return_value = ScrapedPage(
            url="https://timeout.com",
            status_code=0,
            html="",
            text="",
            error="Connection timeout",
        )
        ws_server._scraper = mock_scraper
        client = MCPTestClient(ws_server.mcp)
        result = await client.call_tool("scrape_url", {"url": "https://timeout.com"})
        assert "Error" in result
        assert "timeout" in result.lower()

    async def test_scrape_no_meta_description(self, mock_scraper):
        mock_scraper.scrape.return_value = ScrapedPage(
            url="https://example.com",
            status_code=200,
            html="<html><body>Simple</body></html>",
            text="Simple",
            title="Simple Page",
            links=[],
            meta={},
        )
        ws_server._scraper = mock_scraper
        client = MCPTestClient(ws_server.mcp)
        result = await client.call_tool("scrape_url", {"url": "https://example.com"})
        assert "Simple Page" in result
        assert "**Description:**" not in result


class TestExtractDataTool:
    async def test_extract_returns_json(self, configured_server):
        result = await configured_server.call_tool(
            "extract_data",
            {"url": "https://example.com", "description": "product names and prices"},
        )
        assert "Extracted from" in result or "extracted" in result.lower()

    async def test_extract_with_schema(self, mock_scraper):
        llm = MockExtractorLLM()
        llm.add_response("widget", '{"name": "Widget", "price": 9.99}')
        ws_server.configure(llm=llm, requests_per_second=100, respect_robots=False)
        ws_server._scraper = mock_scraper
        client = MCPTestClient(ws_server.mcp)
        result = await client.call_tool(
            "extract_data",
            {
                "url": "https://example.com",
                "description": "product info",
                "schema": {"name": "string", "price": "number"},
            },
        )
        assert "```json" in result or "Extracted from" in result

    async def test_extract_error_on_scrape_failure(self, mock_scraper):
        mock_scraper.scrape.return_value = ScrapedPage(
            url="https://bad.com",
            status_code=404,
            html="",
            text="",
            error="Not Found",
        )
        ws_server._scraper = mock_scraper
        client = MCPTestClient(ws_server.mcp)
        result = await client.call_tool(
            "extract_data",
            {"url": "https://bad.com", "description": "anything"},
        )
        assert "Error" in result

    async def test_extract_json_parse_failure_returns_error(self, mock_scraper):
        """LLM returning invalid JSON should produce an extraction error."""
        llm = MockExtractorLLM()
        llm.add_response("test", "this is not json at all {{{")
        ws_server.configure(llm=llm, requests_per_second=100, respect_robots=False)
        ws_server._scraper = mock_scraper
        client = MCPTestClient(ws_server.mcp)
        result = await client.call_tool(
            "extract_data",
            {"url": "https://example.com", "description": "test content"},
        )
        assert "error" in result.lower() or "json" in result.lower()


class TestToolListing:
    async def test_has_expected_tools(self, configured_server):
        tools = await configured_server.list_tools()
        names = {t["name"] for t in tools}
        assert "scrape_url" in names
        assert "extract_data" in names

    async def test_tools_have_descriptions(self, configured_server):
        tools = await configured_server.list_tools()
        for tool in tools:
            assert tool["description"], f"Tool {tool['name']} missing description"


class TestMockModeWarning:
    def test_main_warns_extraction_uses_placeholder_llm(self, monkeypatch, caplog):
        """Page fetching is real, but LLM extraction defaults to a stub —
        main() must say so loudly, not silently return stub data."""
        import logging

        monkeypatch.setattr(ws_server.mcp, "run", lambda: None)

        with caplog.at_level(logging.WARNING, logger="mcp_toolkit.servers.web_scraping.server"):
            ws_server.main()

        assert "DefaultLLMProvider" in caplog.text
