# Pre-commit Hook Guide

JAOT uses `pre-commit` (Python tool) to enforce lint and import-boundary
checks before every commit — the same gates that CI runs.

## First-time setup

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files   # one-time sweep
```

`pre-commit install` writes `.git/hooks/pre-commit`. From this point forward,
`git commit` invokes the hooks automatically.

## What runs

- **ruff --fix** — lint + autofix for `.py` files under `app/`, `scripts/`, `deploy/`, `tests/`
- **ruff-format** — formatter check (matches CI `ruff format --check`)
- **lint-imports** — import-linter contracts from `pyproject.toml`

Hooks are HARD-BLOCKING. A failing hook aborts the commit.

## Emergency bypass

For genuine emergencies (hotfix blocked, unrelated lint failure mid-merge):

```bash
git commit --no-verify -m "..."
```

Bypassing a hook is a red flag — open a follow-up task to fix the
underlying lint failure. CI will still run the same gates; a bypassed
commit that fails CI is the worst of both worlds.

## Troubleshooting

- **lint-imports: command not found** — The `language: python` hook installs
  `import-linter` into its own venv on first run. If you see this error, run
  `pre-commit clean && pre-commit install --install-hooks` to rebuild the
  hook environments.
- **Version drift with CI** — The ruff version in `.pre-commit-config.yaml`
  is pinned. If CI uses a newer ruff and reports violations pre-commit did
  not, bump the `rev:` in `.pre-commit-config.yaml` to match.
