import ipaddress
import socket

import httpx
import pytest

from mcp_toolkit.framework.net_safety import validate_global_url
from mcp_toolkit.framework.testing import MCPTestClient
from mcp_toolkit.servers.web_scraping import server
from mcp_toolkit.servers.web_scraping.scraper import WebScraper


@pytest.mark.parametrize(
    "address", ["64:ff9b::7f00:1", "64:ff9b::a9fe:a9fe", "::127.0.0.1", "::ffff:0:127.0.0.1"]
)
def test_embedded_non_global_ipv4_is_refused(monkeypatch, address):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (address, 80, 0, 0))],
    )
    with pytest.raises(ValueError, match="restricted"):
        validate_global_url("http://public-name.example/")


@pytest.mark.asyncio
async def test_redirect_limit_error_omits_location_credentials():
    sentinel = "review-location-credential-sentinel"

    def handler(request):
        return httpx.Response(302, headers={"location": "http://8.8.8.8/?token=" + sentinel})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        page = await WebScraper(respect_robots=False, requests_per_second=0).scrape(
            "http://8.8.8.8/", client=client
        )
    assert page.error and "redirect" in page.error.lower()
    assert sentinel not in page.error


@pytest.mark.parametrize("tool", ["scrape_url", "extract_data"])
@pytest.mark.asyncio
async def test_private_redirect_refusal_is_a_protocol_error(monkeypatch, tool):
    seen = []

    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})

    scraper = WebScraper(respect_robots=False, requests_per_second=0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:

        class BoundScraper:
            async def scrape(self, url, **kwargs):
                return await scraper.scrape(url, client=client, **kwargs)

        monkeypatch.setattr(server, "_scraper", BoundScraper())
        args = {"url": "http://8.8.8.8/"}
        if tool == "extract_data":
            args["description"] = "extract products"
        result = await MCPTestClient(server.mcp).call_tool_result(tool, args)
    assert seen == ["8.8.8.8"]
    assert result.is_error
    assert "169.254.169.254" not in str(result.content)


@pytest.mark.parametrize("client_auth", ["header", "basic"])
@pytest.mark.asyncio
async def test_redirect_does_not_forward_client_credentials_to_another_origin(
    monkeypatch, client_auth
):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80))],
    )
    seen = []

    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(302, headers={"location": "https://other.example/landed"})
        return httpx.Response(200, text="landed")

    kwargs = {"headers": {"Cookie": "session=synthetic-cookie-sentinel"}}
    if client_auth == "header":
        kwargs["headers"]["Authorization"] = "Bearer synthetic-test-only"
    else:
        kwargs["auth"] = httpx.BasicAuth("synthetic-user", "synthetic-password")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs) as client:
        page = await WebScraper(respect_robots=False, requests_per_second=0).scrape(
            "https://first.example/", client=client
        )
    assert page.is_success
    assert "authorization" in seen[0].headers
    assert "authorization" not in seen[1].headers
    assert "cookie" not in seen[1].headers


def _is_ip_literal(host) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def test_idna_check_resolves_the_http_client_hostname(monkeypatch):
    checked = []

    def dns(host, *args, **kwargs):
        checked.append(host)
        ip = "169.254.169.254" if host == "xn--strae-oqa.example" else "8.8.8.8"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80))]

    monkeypatch.setattr(socket, "getaddrinfo", dns)
    with pytest.raises(ValueError, match="restricted"):
        validate_global_url("http://straße.example/latest")
    # Record the host exactly as passed: the point is that the code resolves the
    # ASCII/IDNA hostname httpx connects to, exactly once — not the raw unicode
    # form. Background lookups on shared threads (loopback connects from other
    # tests) also pass through this global socket entry point and resolve IP
    # literals, so only hostname lookups are the code under test. Without that
    # filter this assertion flakes on loaded CI runners.
    assert [h for h in checked if not _is_ip_literal(h)] == ["xn--strae-oqa.example"]


@pytest.mark.parametrize("consumer", ["scraper", "webhook"])
@pytest.mark.asyncio
async def test_dns_lookup_does_not_block_other_async_tasks(monkeypatch, consumer):
    import asyncio
    import threading
    from unittest.mock import MagicMock
    from mcp_toolkit.framework.a2a_adapter import A2AAdapter, A2ATaskStatus

    released = threading.Event()
    observed = []

    def dns(*args, **kwargs):
        observed.append(released.wait(0.3))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80))]

    monkeypatch.setattr(socket, "getaddrinfo", dns)
    original = httpx.AsyncClient

    def make_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(lambda request: httpx.Response(200, text="ok"))
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", make_client)
    if consumer == "scraper":
        task = asyncio.create_task(
            WebScraper(respect_robots=False, requests_per_second=0).scrape("http://public.example/")
        )
    else:
        adapter = A2AAdapter(MagicMock(), base_url="https://bridge.example")
        task = asyncio.create_task(
            adapter._notify(A2ATaskStatus("id", "completed"), "http://public.example/hook")
        )
    await asyncio.sleep(0)
    released.set()
    await task
    assert observed and all(observed)


@pytest.mark.asyncio
async def test_webhook_redirect_is_never_followed(monkeypatch):
    from unittest.mock import MagicMock
    from mcp_toolkit.framework.a2a_adapter import A2AAdapter, A2ATaskStatus

    seen = []

    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
    )
    original = httpx.AsyncClient

    def client(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        k["follow_redirects"] = True
        return original(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    await A2AAdapter(MagicMock(), base_url="https://bridge.example")._notify(
        A2ATaskStatus("id", "completed"), "https://public.example/hook"
    )
    assert seen == ["public.example"]


@pytest.mark.parametrize("tool", ["scrape_url", "extract_data"])
@pytest.mark.asyncio
async def test_first_hop_refusal_is_generic_in_protocol_and_logs(monkeypatch, caplog, tool):
    monkeypatch.setattr(server, "_scraper", WebScraper(respect_robots=False))
    sentinel = "query-credential-sentinel"
    args = {"url": "http://169.254.169.254/?token=" + sentinel}
    if tool == "extract_data":
        args["description"] = "extract products"
    result = await MCPTestClient(server.mcp).call_tool_result(tool, args)
    assert result.is_error
    assert "Unable to scrape page" in str(result.content)
    assert "169.254.169.254" not in str(result.content) + caplog.text
    assert sentinel not in str(result.content) + caplog.text


@pytest.mark.asyncio
async def test_same_origin_redirect_retains_authorization():
    seen = []

    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(302, headers={"location": "/landed"})
        return httpx.Response(200, text="landed")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer synthetic-same-origin"},
    ) as client:
        page = await WebScraper(respect_robots=False, requests_per_second=0).scrape(
            "https://8.8.8.8/", client=client
        )
    assert page.is_success
    assert len(seen) == 2
    assert all(r.headers.get("authorization") == "Bearer synthetic-same-origin" for r in seen)


@pytest.mark.parametrize("status", [300, 304, 305])
@pytest.mark.asyncio
async def test_non_redirect_status_does_not_follow_location(status):
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(status, headers={"location": "http://8.8.4.4/unused"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        page = await WebScraper(respect_robots=False, requests_per_second=0).scrape(
            "https://8.8.8.8/", client=client
        )
    assert len(seen) == 1
    assert page.status_code == status


@pytest.mark.asyncio
async def test_unicode_webhook_uses_canonical_dns_and_issues_no_request(monkeypatch):
    from unittest.mock import MagicMock
    from mcp_toolkit.framework.a2a_adapter import A2AAdapter, A2ATaskStatus

    checked = []

    def dns(host, *a, **k):
        encoded = host.encode("idna") if isinstance(host, str) else host
        checked.append(encoded)
        ip = "169.254.169.254" if encoded == b"xn--strae-oqa.example" else "8.8.8.8"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80))]

    monkeypatch.setattr(socket, "getaddrinfo", dns)
    requested = []

    async def send(*args, **kwargs):
        requested.append(True)
        raise AssertionError("No request may be sent")

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    await A2AAdapter(MagicMock(), base_url="https://bridge.example")._notify(
        A2ATaskStatus("id", "completed"), "http://straße.example/hook"
    )
    assert checked == [b"xn--strae-oqa.example"]
    assert requested == []
