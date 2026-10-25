# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| main (source install) | Yes |
| 0.3.x   | Yes       |
| 0.2.x and older | No |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report vulnerabilities by emailing the maintainer directly. Include:
- A description of the vulnerability and its potential impact
- Steps to reproduce or proof-of-concept code
- The version of `mcp-server-toolkit` affected

If confirmed, a patch will be released as soon as possible and you will be credited in the release notes unless you prefer to remain anonymous.

## Security Practices

- Dependencies are pinned with a `uv.lock` lockfile for reproducible installs
- CVE tracking: critical dependency vulnerabilities are patched in the next release
- API keys and secrets must be passed via environment variables, never hardcoded
- The web scraping server refuses non-http(s) schemes and any host that resolves to a non-global address (private, loopback, link-local including cloud metadata, CGNAT, multicast, IPv4-mapped and NAT64 forms). Redirects are followed by the scraper, not by httpx, and every hop, including the robots.txt fetch, is checked again and connected to the IP that was checked, so a redirect or a DNS rebind cannot reach an internal address.
