"""Web scraper with httpx + BeautifulSoup, robots.txt respect, and rate limiting."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx


@dataclass
class ScrapedPage:
    """Result of scraping a single URL."""

    url: str
    status_code: int
    html: str
    text: str
    title: str = ""
    links: list[str] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)
    scraped_at: float = field(default_factory=time.time)
    error: str | None = None

    @property
    def is_success(self) -> bool:
        return self.status_code == 200 and self.error is None


class RobotsChecker:
    """Simple robots.txt checker."""

    def __init__(self) -> None:
        self._cache: dict[str, set[str]] = {}

    async def is_allowed(self, url: str, client: httpx.AsyncClient) -> bool:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"

        if base not in self._cache:
            try:
                resp = await client.get(f"{base}/robots.txt", timeout=5.0)
                disallowed: set[str] = set()
                if resp.status_code == 200:
                    user_agent_match = False
                    for line in resp.text.split("\n"):
                        line = line.strip()
                        if line.lower().startswith("user-agent:"):
                            agent = line.split(":", 1)[1].strip()
                            user_agent_match = agent == "*"
                        elif user_agent_match and line.lower().startswith("disallow:"):
                            path = line.split(":", 1)[1].strip()
                            if path:
                                disallowed.add(path)
                self._cache[base] = disallowed
            except Exception:
                self._cache[base] = set()

        for path in self._cache[base]:
            if parsed.path.startswith(path):
                return False
        return True


class WebScraper:
    """Agent-driven web scraper with rate limiting and robots.txt respect.

    Args:
        requests_per_second: Max requests per second (default 1.0)
        respect_robots: Whether to check robots.txt (default True)
        timeout: Request timeout in seconds (default 30)
        user_agent: User-Agent header string
    """

    def __init__(
        self,
        requests_per_second: float = 1.0,
        respect_robots: bool = True,
        timeout: float = 30.0,
        user_agent: str = "MCPToolkit-Scraper/0.1",
    ) -> None:
        self._rate_delay = 1.0 / requests_per_second if requests_per_second > 0 else 0
        self._respect_robots = respect_robots
        self._timeout = timeout
        self._user_agent = user_agent
        self._robots = RobotsChecker()
        self._last_request_time: float = 0

    async def _rate_limit(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self._rate_delay:
            await asyncio.sleep(self._rate_delay - elapsed)
        self._last_request_time = time.monotonic()

    async def scrape(
        self,
        url: str,
        css_selector: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> ScrapedPage:
        """Scrape a URL and return structured content."""
        should_close = client is None
        if client is None:
            client = httpx.AsyncClient(
                headers={"User-Agent": self._user_agent},
                follow_redirects=True,
                timeout=self._timeout,
            )

        try:
            if self._respect_robots:
                allowed = await self._robots.is_allowed(url, client)
                if not allowed:
                    return ScrapedPage(
                        url=url,
                        status_code=403,
                        html="",
                        text="",
                        error="Blocked by robots.txt",
                    )

            await self._rate_limit()
            response = await client.get(url)

            html = response.text
            text, title, links, meta = self._parse_html(html, url, css_selector)

            return ScrapedPage(
                url=str(response.url),
                status_code=response.status_code,
                html=html,
                text=text,
                title=title,
                links=links,
                meta=meta,
            )
        except Exception as e:
            return ScrapedPage(
                url=url,
                status_code=0,
                html="",
                text="",
                error=str(e),
            )
        finally:
            if should_close:
                await client.aclose()

    def _parse_html(
        self, html: str, base_url: str, css_selector: str | None = None
    ) -> tuple[str, str, list[str], dict[str, str]]:
        """Parse HTML content, extracting text, title, links, and metadata."""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return html, "", [], {}

        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        title = soup.title.string.strip() if soup.title and soup.title.string else ""

        if css_selector:
            elements = soup.select(css_selector)
            text = "\n".join(el.get_text(strip=True) for el in elements)
        else:
            text = soup.get_text(separator="\n", strip=True)

        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            abs_url = urljoin(base_url, href)
            if abs_url.startswith(("http://", "https://")):
                links.append(abs_url)

        meta: dict[str, str] = {}
        for tag in soup.find_all("meta"):
            name = tag.get("name", "") or tag.get("property", "")
            content = tag.get("content", "")
            if name and content:
                meta[name] = content

        return text, title, links[:50], meta
