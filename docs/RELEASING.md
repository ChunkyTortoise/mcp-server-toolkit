# Releasing

How a version of mcp-server-toolkit goes from this repository to PyPI, and what must flip in the
docs when it does. Publishing is an owner action; everything else here is preparable by any
contributor.

## Release state (2026-10-25)

- Repository: `0.4.0` (tag `v0.4.0` pushed; it is a source snapshot of this version).
- PyPI: serves `0.1.0`, a different, older package body whose metadata advertises servers this
  repository does not contain (`pypi-version` in [claims.yaml](claims.yaml)). The Quickstart
  installs from source for that reason.
- Publishing: PyPI Trusted Publishing (OIDC) through `.github/workflows/publish.yml` — no API
  token. Until that workflow lands, `publish.yml` still carries the legacy token path, whose
  manual attempt failed with 403 because the secret was missing.

## One-time setup (owner)

1. Land the trusted-publishing `publish.yml` (open PR #77 carries the same switch; the copy in
   this repository adds a `workflow_dispatch` trigger because the `v0.4.0` tag predates the
   workflow — see below).
2. On PyPI → project *mcp-server-toolkit* → Publishing → add a Trusted Publisher: repository
   `ChunkyTortoise/mcp-server-toolkit`, workflow `publish.yml`, environment `release`. These
   values must match the workflow exactly; a mismatch is the classic 403.
3. On GitHub → Settings → Environments → create `release` (add required reviewers if you want a
   manual approval before any publish; it also gates the manual trigger).
4. Decide what happens to the misleading `0.1.0` entry. PyPI cannot edit a published description,
   so either yank `0.1.0` (it stays installable only by exact pin) or let `0.4.0` supersede it as
   the latest release. Yanking protects `pip install mcp-server-toolkit` from resolving to the
   wrong package body before `0.4.0` is up.

## Tag timing for 0.4.0

`v0.4.0` was pushed before `publish.yml` existed, so the push event that would trigger the
workflow has already passed. Pick one before publishing:

- **Recommended:** run the Publish workflow by hand (Actions → Publish to PyPI → Run workflow)
  on the `v0.4.0` ref. Nothing public is rewritten, and the `release` environment still gates it.
- Or re-push the tag so its push event fires: `git push origin :v0.4.0 && git push origin v0.4.0`.
  Owner call only: it rewrites a public tag.

## Before publishing

- [ ] `origin/main` contains the full `0.4.0` line (mcp 2.x migration: PRs #73, #74, #75; docs
      release line: #76).
- [ ] Gates green on the release commit: `pytest tests/` with the coverage floor,
      `ruff check mcp_toolkit tests`, `pyright mcp_toolkit`, `python evals/run_evals.py`.
- [ ] `python scripts/check_claims.py --check` passes, and every claim that changes at publish
      time is ready to refresh.
- [ ] `CHANGELOG.md` describes what actually ships in this version.
- [ ] `pyproject.toml` `version` matches the tag and the description matches the changelog.
- [ ] `hatch build && twine check dist/*` is clean, and the wheel installs and imports in a clean
      venv (CI runs this on every push).

## Publish (owner)

- [ ] Trusted publisher configured and `release` environment exists (one-time setup above).
- [ ] Publish from the `v0.4.0` tag using the chosen trigger. Watch the workflow to completion.
- [ ] PyPI shows `0.4.0` with the expected description and both sdist and wheel.

## Same-day truth flip

The docs deliberately say PyPI serves `0.1.0`. The moment that stops being true, these must
change together:

- [ ] `docs/claims.yaml`: refresh `pypi-version` to `0.4.0` with its verification command and
      today's date.
- [ ] `README.md`: replace the "PyPI package is an early 0.1.0 preview" notes (Quickstart and
      Methodology & limits) with the plain `pip install mcp-server-toolkit` path.
- [ ] `.claude/CLAUDE.md` Deploy section.
- [ ] `python scripts/check_claims.py --check` again.
- [ ] Create the GitHub release object for `v0.4.0`.

## Failure modes seen so far

- **403 on upload:** the first publish attempt failed because `PYPI_API_TOKEN` was missing; that
  path is now legacy. Under OIDC a 403 means the trusted-publisher tuple (owner/repo, workflow
  file name, environment) does not match what PyPI has registered.
- **Workflow not firing on tag push:** the tag predates the workflow (see above), or the pushed
  tag does not match `v*`.
