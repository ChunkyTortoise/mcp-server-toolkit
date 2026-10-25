"""Web scraper with httpx + BeautifulSoup, robots.txt respect, and rate limiting."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx


_MAX_REDIRECTS = 5
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _is_forbidden_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for anything that is not a globally routable unicast address."""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip in _NAT64:
            ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return not ip.is_global or ip.is_multicast or getattr(ip, "is_site_local", False)


def _resolve_public(url: str) -> str:
    """Validate scheme and host, and return one IP the request must connect to.

    Every resolved address must be public, so a mixed DNS answer is refused
    rather than raced. Callers connect to the returned IP, so a second lookup
    (DNS rebinding) cannot swap in a private address after this check.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme {parsed.scheme!r} not allowed. Only http/https permitted.")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")

    try:
        results = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise ValueError(f"Could not resolve hostname {hostname!r}: {e}")
    addresses = [ipaddress.ip_address(result[4][0]) for result in results]
    if not addresses:
        raise ValueError(f"Could not resolve hostname {hostname!r}")
    for ip in addresses:
        if _is_forbidden_ip(ip):
            raise ValueError(f"URL resolves to private/restricted IP: {ip}")
    return str(addresses[0])


def _validate_url(url: str) -> None:
    """Reject file://, non-http schemes, and private/metadata IPs."""
    _resolve_public(url)


def _origin(url: httpx.URL) -> tuple[str, str, int | None]:
    return url.scheme, url.host, url.port


async def _safe_get(
    client: httpx.AsyncClient,
    url: str,
    timeout: float | None = None,
) -> tuple[httpx.Response, str]:
    """GET with every redirect hop validated and pinned to its checked IP.

    Redirects are followed here, never by httpx, whatever the client was built
    with. Like httpx, credentials from the client (Authorization, Cookie) are
    dropped once a hop leaves the original origin. Returns the response and the
    hostname-based URL it came from.
    """
    current = url
    origin = _origin(httpx.URL(url))
    for _ in range(_MAX_REDIRECTS + 1):
        ip = _resolve_public(current)
        target = httpx.URL(current)
        extensions = {"sni_hostname": target.host} if target.scheme == "https" else {}
        request = client.build_request(
            "GET",
            target.copy_with(host=ip),
            headers={"Host": target.netloc.decode("ascii")},
            extensions=extensions,
            timeout=httpx.USE_CLIENT_DEFAULT if timeout is None else timeout,
        )
        if _origin(target) != origin:
            request.headers.pop("authorization", None)
            request.headers.pop("cookie", None)
        response = await client.send(request, follow_redirects=False)
        location = response.headers.get("location")
        if response.status_code not in _REDIRECT_STATUSES or not location:
            return response, current
        await response.aclose()
        current = urljoin(current, location)
    raise ValueError(f"Too many redirects (limit {_MAX_REDIRECTS})")


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
                resp, _ = await _safe_get(client, f"{base}/robots.txt", timeout=5.0)
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
        _validate_url(url)
        should_close = client is None
        if client is None:
            client = httpx.AsyncClient(
                headers={"User-Agent": self._user_agent},
                follow_redirects=False,
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
            response, final_url = await _safe_get(client, url)

            html = response.text
            text, title, links, meta = self._parse_html(html, url, css_selector)

            return ScrapedPage(
                url=final_url,
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
            href = str(a["href"])
            abs_url = urljoin(base_url, href)
            if abs_url.startswith(("http://", "https://")):
                links.append(abs_url)

        meta: dict[str, str] = {}
        for tag in soup.find_all("meta"):
            name = str(tag.get("name", "") or tag.get("property", ""))
            content = str(tag.get("content", ""))
            if name and content:
                meta[name] = content

        return text, title, links[:50], meta
