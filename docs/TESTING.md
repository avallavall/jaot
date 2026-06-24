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
| Backend test functions | **2,800+** across 186 files (more at runtime via parametrization) |
| Line coverage (`app/`) | **79.7%**, enforced in CI at `--cov-fail-under=78` |
| API routes mapped | 222 (≈52 org-scoped, 30 financial) |
| Database in tests | real PostgreSQL — never mocked |
| Frontend | ESLint + i18n consistency + Vitest unit tests |

## What gets tested hardest

The money and the multi-tenancy paths get the most scrutiny:

- **Financial flows** (credits, refunds, Stripe) — concurrency tests, idempotency
  tests, invalid-amount tests. Refunds are idempotent at the database level (a
  partial unique index), and there's a test that proves a double-refund attempt
  is rejected rather than double-crediting.
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
| Stripe service | **97.5%** |
| Credits service | **94.6%** |
| Auth, solver core | ≥75% target met |

(Target is ≥75% per file; residual survivors are documented cosmetic/equivalent
mutants, not unasserted behaviour.)

## Architectural boundaries

Domain boundaries aren't a convention — they're enforced. Five `import-linter`
contracts run in the test toolchain; the key one keeps `pyscipopt` confined to
the solver adapter layer, so the solver-agnostic core physically cannot import a
specific solver. A boundary violation fails the check.

## Continuous integration

Two pipelines, by design:

- **Public CI** (`.github/workflows/ci.yml`, runs on any GitHub runner, no
  secrets): `ruff` lint + format, backend `pytest` with the 78% coverage gate
  against a real PostgreSQL service, frontend ESLint + i18n check + Vitest. This
  is what runs on your PR.
- **Maintainer pipeline** (runs on the maintainer's self-hosted CI runner): all of
  the above plus `bandit`, `pip-audit`, `npm audit`, Lighthouse budgets, image
  builds, and the production deploy.

## Run it yourself

```bash
# Backend (needs a PostgreSQL on :5432; docker compose up -d postgres is enough)
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/                          # full suite against real PostgreSQL
pytest tests/ --cov=app --cov-report=term-missing   # with coverage
ruff check app/ && ruff format --check app/
lint-imports                           # import-linter boundary contracts

# Frontend (in frontend/)
npm ci
npm run lint && npm run check-i18n
npm run test                           # Vitest
npm run test:e2e                       # Playwright (needs the stack up)
```

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full development setup.
