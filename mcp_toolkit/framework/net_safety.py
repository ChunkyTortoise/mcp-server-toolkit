"""Shared check for outbound HTTP and HTTPS URLs."""

from __future__ import annotations

import ipaddress
import socket

import httpx

# These standard translation forms carry IPv4 in the last 32 bits.
_IPV4_TRANSLATION_NETWORKS = tuple(
    ipaddress.IPv6Network(prefix) for prefix in ("64:ff9b::/96", "::/96", "::ffff:0:0:0/96")
)


def is_forbidden_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for anything that is not a globally routable unicast address.

    IPv6 forms that embed an IPv4 address (mapped, NAT64, compatible, 6to4) are
    classified by the embedded address as well as by the IPv6 address itself.
    """
    address = ip
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = ip.ipv4_mapped or ip.sixtofour
        if embedded is None and any(ip in net for net in _IPV4_TRANSLATION_NETWORKS):
            embedded = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        address = embedded or ip
    # is_global alone also admits multicast and deprecated IPv6 site-local.
    site_local = isinstance(address, ipaddress.IPv6Address) and address.is_site_local
    return not ip.is_global or not address.is_global or address.is_multicast or site_local


def resolve_public_ip(url: str, *, detail: bool = False) -> str:
    """Validate scheme and host, and return one global IP for the URL's host.

    Every resolved address must be global, so a mixed DNS answer is refused.
    With detail=False the error messages never include the address. With
    detail=True they name it, for library callers that report to a developer.

    Callers that connect to the returned IP literal are not exposed to DNS
    rebinding. Callers that discard it (validate_global_url) are: the hostname
    is resolved here and again at connect time, a TOCTOU gap, so a resolver can
    answer differently the second time.
    """
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL:
        raise ValueError("Invalid outbound URL") from None
    if parsed.scheme not in ("http", "https"):
        if detail:
            raise ValueError(
                f"URL scheme {parsed.scheme!r} not allowed. Only http/https permitted."
            )
        raise ValueError("URL scheme not allowed. Only http/https permitted.")

    # Resolve exactly the ASCII hostname HTTPX will connect to (IDNA 2008).
    hostname = parsed.raw_host.decode("ascii")
    if not hostname:
        raise ValueError("URL has no hostname")

    try:
        results = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        if detail:
            raise ValueError(f"Could not resolve hostname {hostname!r}: {exc}") from None
        raise ValueError("Could not resolve URL hostname") from None

    addresses = [ipaddress.ip_address(result[4][0]) for result in results]
    if not addresses:
        raise ValueError("No addresses resolved for URL hostname")
    for ip in addresses:
        if is_forbidden_ip(ip):
            if detail:
                raise ValueError(f"URL resolves to private/restricted IP: {ip}")
            raise ValueError("URL resolves to a private/restricted address")
    return str(addresses[0])


def validate_global_url(url: str) -> None:
    """Reject non-http(s) URLs and hosts that resolve to a non-global address."""
    resolve_public_ip(url)
