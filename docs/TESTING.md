# Testing & Quality

JAOT's headline claim is "AI-accelerated, gated by tests and CI." This is the
part you can verify rather than take on faith. Everything below is reproducible
from a clean checkout.

## Philosophy

- **No mocked database.** Every backend test runs against a real PostgreSQL
  instance (a `jaot_test` database, auto-created). If a query is wrong, the test
  fails — there is no mock to paper over it.
- **Auth is always on in tests.** There is no auth-bypass flag. Tests
  authenticate with real API keys via `authenticated_client` / `admin_client`
  fixtures, exactly like a real client.
- **Fix the code, not the test.** Assertions are never weakened, tests never
  skipped, and auth never disabled to make a suite go green.
- **Every endpoint tests its rejection paths**, not just the happy path —
  401/403, expired tokens, missing headers, cross-tenant access, invalid input.

## By the numbers

| | |
|---|---|
| Backend tests | **4,410** collected across 242 files (965 test functions; the rest are parametrizations) |
| Line coverage (`app/`) | **87.0%**, enforced in CI at `--cov-fail-under=78` |
| API surface | 194 paths / 238 operations, counted from the OpenAPI schema |
| Database in tests | real PostgreSQL — never mocked |
| Frontend | ESLint + i18n consistency + Vitest unit tests |

## What gets tested hardest

The solve and multi-tenancy paths get the most scrutiny:

- **Solve flows** — concurrency and idempotency tests. A duplicate
  `Idempotency-Key` provably attaches to the original run (same
  `execution_id`, exactly one `ModelExecution` row) instead of re-solving,
  and the worker↔reaper terminal-wins race is pinned by a CONTRACT-TEST.
- **Multi-tenancy** — every org-scoped endpoint has a cross-tenant rejection
  test; an authenticated user from org B cannot read org A's data.
- **Locking & concurrency** — concurrent-access tests are mandatory for the
  flows that take row locks.

Invariant-encoding tests are annotated `# CONTRACT-TEST: <invariant>` so they
survive test-consolidation passes.

## Mutation testing

Line coverage proves a line *ran*; it doesn't prove a test would *catch a bug*
on that line. So the critical modules are mutation-tested (mutmut): the tool
mutates the source and checks that some test fails. Scores on the modules that
matter most:

| Module | Mutation score |
|---|---|
| Idempotency service | **100%** |
| Auth, solver core | ≥75% target met |

Target is ≥75% per file; residual survivors are documented cosmetic/equivalent
mutants, not unasserted behaviour. Seven files are targeted, listed in
`[tool.mutmut]` in `pyproject.toml`.

A mutation config is only as good as its paths. Ours had gone stale: it still
named the credits, Stripe and invoice services, deleted with ADR-008, and every
one of the eleven test files it selected had been deleted too — so a run
selected no tests and no mutant could be killed. Cleaned 2026-08-26. If you add
a target, check the tests you select for it still exist.

## The frontend's API types cannot drift

`frontend/src/lib/generated/api.ts` is generated from the backend's OpenAPI
schema and committed. The `types-frontend` CI job regenerates it from the code
in the checkout and fails if it differs from what is committed.

It exists because nothing verified that file, and the only thing that
regenerated it was `npm run build`'s prebuild step, which curls
`http://localhost:8001` and prints "API not running, skipping type generation"
when nothing answers. Two of its three outcomes are wrong: nothing running
leaves the drift in place, and an **old** API container silently overwrites
correct types with old ones. The Docker image build can never reach the API, so
production ships whatever is committed — and `tsc` then validates the frontend
against a stale contract and passes clean while the two sides disagree.

To fix a failure:

```bash
python scripts/export_openapi.py
cd frontend && npm run generate-types
```

`scripts/export_openapi.py` calls `app.openapi()` directly, so it needs no
running server and no reachable database.

## Architectural boundaries

Domain boundaries aren't a convention — they're enforced. Seven `import-linter`
contracts run as their own CI job (`lint-imports`); the key one keeps
`pyscipopt` confined to the solver adapter layer, so the solver-agnostic core
physically cannot import a specific solver. A boundary violation fails the
build.

## Continuous integration

Two workflows, and everything that judges a change is in the public one.

**`.github/workflows/ci.yml`** — six independent jobs on GitHub-hosted runners,
no secrets. This is what runs on your PR:

| Job | What it gates |
|---|---|
| `lint-backend` | `ruff check` + `ruff format --check` over the five gated directories, then `lint-imports` (7 contracts) |
| `security-backend` | `pip-audit -r requirements.txt` (strict) + `bandit -r app/ -lll` |
| `test-backend` | `pytest` with `--cov-fail-under=78` against a real PostgreSQL service; installs `coinor-cbc` and `glpk-utils` so the CLI-solver tests run instead of skipping |
| `types-frontend` | regenerates `api.ts` from the schema and fails on any difference (see above) |
| `lint-frontend` | ESLint + `check-i18n` + `npm audit` (critical blocks) |
| `test-frontend` | Vitest |

**`.github/workflows/deploy.yml`** — image builds and the production deploy, on
the maintainer's self-hosted runner. It gates nothing; it ships what CI passed.

This section used to say the security scans were maintainer-only and that
Lighthouse budgets ran somewhere. Neither was true: `bandit`, `pip-audit` and
`npm audit` are all in the public CI above, and there is no Lighthouse job.

Not in CI, and both catch things the jobs above do not: `next build` (run it
before opening a PR) and the Playwright E2E suite.

## Run it yourself

```bash
# Backend (needs a PostgreSQL on :5432; docker compose up -d postgres is enough)
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/                          # full suite against real PostgreSQL
pytest tests/ --cov=app --cov-report=term-missing   # with coverage
ruff check app/ infra/ scripts/ deploy/ tests/ && ruff format --check app/ infra/ scripts/ deploy/ tests/
lint-imports                           # import-linter boundary contracts

# Frontend (in frontend/)
npm ci
npm run lint && npm run check-i18n
npm run test                           # Vitest
npm run test:e2e                       # Playwright (needs the stack up)
```

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full development setup.
