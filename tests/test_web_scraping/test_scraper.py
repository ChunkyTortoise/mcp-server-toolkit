"""Tests for WebScraper URL validation (SSRF prevention)."""

import pytest

from mcp_toolkit.servers.web_scraping.scraper import WebScraper, _validate_url


class TestValidateUrl:
    def test_file_scheme_raises(self):
        with pytest.raises(ValueError, match="not allowed"):
            _validate_url("file:///etc/passwd")

    def test_ftp_scheme_raises(self):
        with pytest.raises(ValueError, match="not allowed"):
            _validate_url("ftp://example.com")

    def test_data_scheme_raises(self):
        with pytest.raises(ValueError, match="not allowed"):
            _validate_url("data:text/html,<h1>hi</h1>")

    def test_loopback_raises(self):
        with pytest.raises(ValueError, match="private/restricted"):
            _validate_url("http://127.0.0.1")

    def test_localhost_raises(self):
        with pytest.raises(ValueError, match="private/restricted"):
            _validate_url("http://localhost")

    def test_no_hostname_raises(self):
        with pytest.raises(ValueError, match="no hostname"):
            _validate_url("http://")

    def test_http_public_allowed(self):
        # Should not raise for public URLs
        _validate_url("http://example.com")

    def test_https_public_allowed(self):
        _validate_url("https://example.com")


class TestScraperSSRF:
    """Verify scrape() rejects SSRF targets before making requests."""

    async def test_scrape_file_scheme_raises(self):
        scraper = WebScraper()
        with pytest.raises(ValueError, match="not allowed"):
            await scraper.scrape("file:///etc/passwd")

    async def test_scrape_loopback_raises(self):
        scraper = WebScraper()
        with pytest.raises(ValueError, match="private/restricted"):
            await scraper.scrape("http://127.0.0.1")
