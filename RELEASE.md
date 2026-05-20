# Release Checklist

Process for cutting an `mcp-server-toolkit` release to PyPI. Build backend is
`hatchling`; uploads go through `twine`. Last published tag: `v0.2.0`. Next
intended release: `v0.3.0` (currently `0.3.0.dev0` on `main`).

## Pre-flight (must be green before bumping)

- [ ] Working tree clean: `git status` reports nothing to commit.
- [ ] On `main`, up to date with `origin/main`.
- [ ] Full test suite: `pytest tests/ -q` shows **628 passed, 2 skipped** (or
      higher passed count, never lower). Update the README's "Measured results"
      table if the number changes.
- [ ] Lint: `ruff check .` exits 0.
- [ ] Coverage: `pytest --cov=mcp_toolkit --cov-fail-under=80` exits 0. README
      claims 84%; if measured coverage moves more than +/- 1 point, update the
      README row.
- [ ] Adversarial corpus: `wc -l tests/adversarial/injection_corpus.jsonl`
      matches the README claim (30 cases). Update both if it changes.
- [ ] CI green on `main` for the commit you intend to tag.
- [ ] No `gitleaks` findings outside the path/regex allowlist in
      `.gitleaks.toml` (see SECURITY.md secret-scan triage).

## Version bump

1. Edit `pyproject.toml`: change `version = "0.3.0.dev0"` to `version = "0.3.0"`.
2. Edit `CHANGELOG.md`: confirm the `[0.3.0]` heading carries the actual release
   date (not the original drafting date).
3. Edit `SECURITY.md`: move `0.3.x` from "Unreleased" to "Yes (current)" once
   shipped; mark `0.1.x` as "Yes (previous)" or "No (EOL)" per support policy.
4. Edit `README.md`: replace the "Release status" block with a one-line "Latest
   release: 0.3.0" note, or delete the block entirely once the install command
   resolves to 0.3.0 by default.
5. Commit: `git commit -am "release: 0.3.0"` (do not skip pre-commit hooks).

## Build and smoke-test in a clean venv

```bash
rm -rf dist/ build/
hatch build                    # produces dist/*.whl and dist/*.tar.gz
python -m venv /tmp/mcptk-smoke
source /tmp/mcptk-smoke/bin/activate
pip install dist/mcp_server_toolkit-0.3.0-py3-none-any.whl
python -c "from mcp_toolkit import EnhancedMCP; print(EnhancedMCP('smoke'))"
deactivate
```

Confirm:
- [ ] Wheel installs without resolver conflicts on Python 3.10, 3.11, 3.12.
- [ ] `EnhancedMCP` import succeeds.
- [ ] At least one tool round-trip via `MCPTestClient` works
      (see `tests/test_framework/test_test_client.py` for the pattern).

## Upload (the irreversible step)

This is the only step that publishes anything publicly. PyPI does not allow
re-uploading the same version. Once `twine upload` succeeds, `0.3.0` is locked.

```bash
# TestPyPI dry run first (recommended)
twine upload --repository testpypi dist/*
pip install --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ \
    mcp-server-toolkit==0.3.0
# If smoke passes:
twine upload dist/*
```

`PYPI_API_TOKEN` must be set in the environment or `~/.pypirc`.

## Post-release

1. Tag the commit: `git tag v0.3.0 && git push origin v0.3.0`.
2. Create a GitHub release with the `CHANGELOG.md` `[0.3.0]` section as the
   body. `gh release create v0.3.0 --notes-file <(awk '/## \[0.3.0\]/,/## \[0.2.0\]/' CHANGELOG.md | head -n -1)`.
3. Bump `pyproject.toml` to the next dev version on `main`
   (e.g. `0.4.0.dev0`) and commit: `chore: open 0.4.0 development line`.
4. Verify the PyPI page renders: https://pypi.org/project/mcp-server-toolkit/
5. Update SECURITY.md if not already done.
6. Submit (or refresh) the awesome-mcp-servers entry.

## Rollback policy

PyPI does not support deletion of published releases. If 0.3.0 ships with a
defect:

- Yank the release on PyPI (hides from `pip install` resolution without
  breaking pinned consumers): `pypi-yank mcp-server-toolkit 0.3.0`
  (or use the PyPI web UI: Manage Project > Release > Yank).
- Cut a patch release `0.3.1` with the fix. Do not attempt to re-upload `0.3.0`.

## What not to do during release

- Do not push directly to `main`. All release commits go through a PR.
- Do not skip pre-commit hooks with `--no-verify`. If a hook fails, fix the
  cause and re-commit.
- Do not upload `*.dev0` artifacts to production PyPI. TestPyPI only.
- Do not delete or force-push the release tag once pushed to GitHub.
