# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.2.x   | Yes       |
| 0.1.x   | No        |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report vulnerabilities by emailing the maintainer directly. Include:
- A description of the vulnerability and its potential impact
- Steps to reproduce or proof-of-concept code
- The version of `mcp-server-toolkit` affected

You will receive a response within 48 hours acknowledging the report. If confirmed, a patch will be released as soon as possible and you will be credited in the release notes unless you prefer to remain anonymous.

## Security Practices

- Dependencies are pinned with a `uv.lock` lockfile for reproducible installs
- CVE tracking: critical dependency vulnerabilities are patched in the next release
- API keys and secrets must be passed via environment variables — never hardcoded
- Secret scanning runs against `.gitleaks.toml` (extends the default ruleset)

## Secret-scan triage (2026-05-18)

A full-history `gitleaks` scan reports 16 matches. **All 16 are intentional and
contain no live credentials:**

| Location | What it is |
|----------|------------|
| `evals/quality/tasks.py` | HS256 test secret `eval-secret-long-enough-32ch` used to assert JWT auth correctness |
| `tests/gates/test_gate_safety.py` | A self-describing HS256 test secret and an `alg:none` forged-JWT string used by the safety gate tests |
| `tests/adversarial/injection_corpus.jsonl` | The adversarial corpus — forged/`alg:none` JWTs and fake API keys are the *attack payloads under test* |

These strings are required by the security test suite itself. They are
allowlisted by path/regex in `.gitleaks.toml`. No secret rotation or history
rewrite was needed (verified: the matched commits contain only test fixtures).
Local scan reports are written to `.maintenance/` (gitignored, never committed).
