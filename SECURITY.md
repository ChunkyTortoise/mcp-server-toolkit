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
