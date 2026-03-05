"""Web Scraping MCP Server — Agent-driven web scraping with structured extraction."""

from mcp_toolkit.servers.web_scraping.extractor import DataExtractor
from mcp_toolkit.servers.web_scraping.scraper import ScrapedPage, WebScraper
from mcp_toolkit.servers.web_scraping.server import mcp as web_scraping_server

__all__ = ["web_scraping_server", "WebScraper", "ScrapedPage", "DataExtractor"]
