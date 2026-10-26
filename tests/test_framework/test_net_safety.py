"""One shared outbound address check, with the DNS-rebinding gap named."""

import ipaddress
import socket
from pathlib import Path

import pytest

from mcp_toolkit.framework.net_safety import validate_global_url

ROOT = Path(__file__).resolve().parents[2]


def test_scraper_and_a2a_share_one_helper():
    from mcp_toolkit.framework import a2a_adapter, net_safety
    from mcp_toolkit.servers.web_scraping import scraper

    assert scraper._is_forbidden_ip is net_safety.is_forbidden_ip
    assert a2a_adapter.validate_global_url is net_safety.validate_global_url


def test_dns_rebinding_gap_is_named_without_a_doc_pointer():
    text = (ROOT / "mcp_toolkit/framework/net_safety.py").read_text()
    assert "TOCTOU" in text
    assert "rebinding" in text
    assert "DEPLOYMENT" not in text
    assert ".md" not in text


@pytest.mark.parametrize("address", ["fec0::1", "::ffff:224.0.0.1"])
def test_deprecated_site_local_and_mapped_multicast_are_not_global_destinations(
    monkeypatch, address
):
    import socket
    from mcp_toolkit.framework.net_safety import validate_global_url

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (address, 443, 0, 0))],
    )
    with pytest.raises(ValueError, match="restricted"):
        validate_global_url("https://public-name.example/path")


def test_empty_dns_answer_cannot_authorize_an_outbound_request(monkeypatch):
    import socket
    from mcp_toolkit.framework.net_safety import validate_global_url

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [])
    with pytest.raises(ValueError, match="resolve"):
        validate_global_url("https://public-name.example/path")


_PUBLIC_IP = "93.184.216.34"


def _stub_dns(monkeypatch, mapping: dict[str, str] | None = None) -> None:
    """Answer getaddrinfo locally. Unknown hostnames use one global address."""

    def fake(host, port, *args, **kwargs):
        ip = (mapping or {}).get(host)
        if ip is None:
            try:
                ipaddress.ip_address(host)
            except ValueError:
                ip = _PUBLIC_IP
            else:
                ip = host
        parsed = ipaddress.ip_address(ip)
        family = socket.AF_INET6 if parsed.version == 6 else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake)


class TestNonGlobalAddresses:
    @pytest.mark.parametrize(
        "url",
        [
            "http://100.64.0.1/",
            "http://[::ffff:100.64.0.1]/",
            "http://224.0.0.1/",
            "http://[ff02::1]/",
            "http://[::ffff:224.0.0.1]/",
            "http://[::ffff:127.0.0.1]/",
            "http://[::1]/",
            "http://[fc00::1]/",
        ],
    )
    def test_rejects_non_global_and_multicast(self, url: str):
        with pytest.raises(ValueError, match="private/restricted"):
            validate_global_url(url)

    def test_allows_public_ipv4_literal(self):
        validate_global_url("http://8.8.8.8/")

    def test_allows_public_ipv6_literal(self):
        validate_global_url("http://[2001:4860:4860::8888]/")

    def test_allows_public_ipv4_mapped(self, monkeypatch):
        _stub_dns(monkeypatch, {"mapped.example": "::ffff:8.8.8.8"})
        validate_global_url("http://mapped.example/path")

    def test_rejects_hostname_resolving_to_mapped_cgnat(self, monkeypatch):
        _stub_dns(monkeypatch, {"ok.example": "::ffff:100.64.0.1"})
        with pytest.raises(ValueError, match="private/restricted"):
            validate_global_url("http://ok.example/path")

    def test_rejects_hostname_resolving_to_ipv6_multicast(self, monkeypatch):
        _stub_dns(monkeypatch, {"mcast.example": "ff02::1"})
        with pytest.raises(ValueError, match="private/restricted"):
            validate_global_url("http://mcast.example/")
