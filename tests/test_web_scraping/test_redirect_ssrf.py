"""Redirects cannot reach private or metadata addresses (W3.7).

public.test resolves to a documentation-free public IP served by a mock route.
Every other address goes to a real transport, so a request that escapes the
checks would really reach the loopback "internal" server and bump its counter.
"""

import ipaddress
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from mcp_toolkit.servers.web_scraping import scraper as scraper_module
from mcp_toolkit.servers.web_scraping.scraper import WebScraper, _is_forbidden_ip

PUBLIC_IP = "93.184.216.34"
FAKE_DNS = {
    "public.test": [PUBLIC_IP],
    "other.test": [PUBLIC_IP],
    "metadata.test": ["169.254.169.254"],
    "mixed.test": [PUBLIC_IP, "10.0.0.5"],
}


@pytest.fixture
def internal_server():
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"internal secret")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1], hits
    server.shutdown()
    server.server_close()


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    real = socket.getaddrinfo

    def getaddrinfo(host, *args, **kwargs):
        if host in FAKE_DNS:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in FAKE_DNS[host]]
        return real(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


class Routes(httpx.AsyncBaseTransport):
    """Serve PUBLIC_IP from a route table; send everything else to the network."""

    def __init__(self, routes):
        self.routes = routes
        self.seen = []
        self.real = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request):
        self.seen.append(request)
        if request.url.host == PUBLIC_IP:
            status, headers, body = self.routes.get(request.url.path, (404, {}, b""))
            return httpx.Response(status, headers=headers, content=body)
        return await self.real.handle_async_request(request)


def redirect(location):
    return (302, {"location": location}, b"")


async def scrape(routes, url="http://public.test/start", **client_kwargs):
    transport = Routes(routes)
    async with httpx.AsyncClient(transport=transport, **client_kwargs) as client:
        page = await WebScraper(requests_per_second=0, respect_robots=False).scrape(
            url, client=client
        )
    return page, transport


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target",
    [
        "http://127.0.0.1:{port}/",
        "http://[::1]:{port}/",
        "http://[::ffff:127.0.0.1]:{port}/",
        "http://2130706433:{port}/",
        "http://0x7f000001:{port}/",
        "http://localhost:{port}/",
    ],
)
async def test_redirect_to_loopback_never_reaches_it(internal_server, target):
    port, hits = internal_server
    page, _ = await scrape({"/start": redirect(target.format(port=port))})
    assert page.error and "private/restricted" in page.error
    assert hits == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target", ["http://169.254.169.254/latest/meta-data/", "http://metadata.test/"]
)
async def test_redirect_to_metadata_is_refused_before_any_request(target):
    page, transport = await scrape({"/start": redirect(target)})
    assert page.error and "private/restricted" in page.error
    assert [r.url.host for r in transport.seen] == [PUBLIC_IP]


@pytest.mark.asyncio
async def test_redirect_to_a_host_with_any_private_address_is_refused():
    page, transport = await scrape({"/start": redirect("http://mixed.test/")})
    assert page.error and "10.0.0.5" in page.error
    assert len(transport.seen) == 1


@pytest.mark.asyncio
async def test_redirect_to_a_non_http_scheme_is_refused():
    page, transport = await scrape({"/start": redirect("file:///etc/passwd")})
    assert page.error and "not allowed" in page.error
    assert len(transport.seen) == 1


@pytest.mark.asyncio
async def test_caller_client_with_follow_redirects_still_validates_each_hop(internal_server):
    port, hits = internal_server
    page, _ = await scrape({"/start": redirect(f"http://127.0.0.1:{port}/")}, follow_redirects=True)
    assert page.error and "private/restricted" in page.error
    assert hits == []


@pytest.mark.asyncio
async def test_public_redirect_is_followed_and_pinned_to_the_checked_ip():
    page, transport = await scrape(
        {
            "/start": redirect("/final"),
            "/final": (200, {"content-type": "text/html"}, b"<title>ok</title><p>done</p>"),
        }
    )
    assert page.is_success, page.error
    assert page.url == "http://public.test/final"
    assert page.title == "ok"
    assert [r.url.host for r in transport.seen] == [PUBLIC_IP, PUBLIC_IP]
    assert {r.headers["host"] for r in transport.seen} == {"public.test"}


@pytest.mark.asyncio
async def test_https_keeps_the_hostname_for_sni():
    page, transport = await scrape({"/": (200, {}, b"<p>tls</p>")}, url="https://public.test/")
    assert page.is_success, page.error
    assert transport.seen[0].url.host == PUBLIC_IP
    assert transport.seen[0].extensions["sni_hostname"] == "public.test"


@pytest.mark.asyncio
async def test_client_credentials_are_dropped_on_a_cross_origin_hop():
    page, transport = await scrape(
        {
            "/start": redirect("/same"),
            "/same": redirect("http://other.test/final"),
            "/final": (200, {}, b"<p>done</p>"),
        },
        headers={"Authorization": "Bearer secret"},
        cookies={"session": "secret"},
    )
    assert page.is_success, page.error
    same, _, cross = transport.seen
    assert same.headers["authorization"] == "Bearer secret"
    assert "cookie" in same.headers
    assert cross.headers["host"] == "other.test"
    assert "authorization" not in cross.headers
    assert "cookie" not in cross.headers


@pytest.mark.asyncio
async def test_redirect_loop_stops_at_the_hop_limit():
    page, transport = await scrape({"/start": redirect("/start")})
    assert page.error and "Too many redirects" in page.error
    assert len(transport.seen) == scraper_module._MAX_REDIRECTS + 1


@pytest.mark.asyncio
async def test_robots_txt_redirect_cannot_reach_internal_hosts(internal_server):
    port, hits = internal_server
    transport = Routes(
        {
            "/robots.txt": redirect(f"http://127.0.0.1:{port}/robots.txt"),
            "/page": (200, {}, b"<p>public</p>"),
        }
    )
    async with httpx.AsyncClient(transport=transport) as client:
        page = await WebScraper(requests_per_second=0).scrape(
            "http://public.test/page", client=client
        )
    assert page.is_success, page.error
    assert hits == []


@pytest.mark.parametrize(
    "address",
    [
        "0.0.0.0",
        "100.64.0.1",
        "224.0.0.1",
        "255.255.255.255",
        "fd00::1",
        "fe80::1",
        "fec0::1",
        "ff02::1",
        "::ffff:10.0.0.1",
        "64:ff9b::7f00:1",
    ],
)
def test_non_global_addresses_are_forbidden(address):
    assert _is_forbidden_ip(ipaddress.ip_address(address))


@pytest.mark.parametrize("address", [PUBLIC_IP, "2606:4700:4700::1111", "64:ff9b::808:808"])
def test_global_unicast_addresses_are_allowed(address):
    assert not _is_forbidden_ip(ipaddress.ip_address(address))
