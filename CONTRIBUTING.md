# Contributing to JAOT

Thanks for your interest! JAOT is maintained best-effort by a solo maintainer —
issues and PRs are triaged monthly. Small, focused PRs get reviewed fastest.

## Development setup

```bash
cp .env.example .env
docker-compose up -d          # full dev stack (API on :8001, frontend on :3000)
```

Backend tests run against a real PostgreSQL instance (database `jaot_test`,
auto-created on the same container) — no DB mocking, ever:

```bash
pytest                        # backend tests
ruff check app/               # backend lint
ruff format --check app/      # backend formatting
cd frontend && npm run lint   # frontend lint
cd frontend && npm run test   # frontend unit tests (vitest)
```

Migrations:

```bash
alembic -c infra/alembic.ini upgrade head
alembic -c infra/alembic.ini revision --autogenerate -m "describe the change"
```

## Project conventions

These are enforced by CI (ruff, import-linter, pytest) and by review:

- **IDs** are prefixed strings — `generate_id("org_")`, never raw UUIDs in
  persisted records.
- **Datetimes** come from `utcnow()` in `app/shared/utils/datetime_helpers.py`,
  never `datetime.now()`.
- **Multi-tenancy:** every org-scoped query must filter by `organization_id`.
  A missing filter is a security bug, not a style issue.
- **ORM:** SQLAlchemy 2.0 typed mappings (`Mapped[str]`, `mapped_column()`),
  not legacy `Column()`.
- **FastAPI dependencies:** import `DBSession`, `CurrentUser`, `CurrentOrg`,
  `AdminUser` from `app/api/deps.py` — don't construct sessions or resolve
  auth manually.
- **Middleware:** pure ASGI only, never `BaseHTTPMiddleware`.
- **Auth is always on.** There is no bypass flag. Public routes are an explicit
  allowlist (`PUBLIC_PATHS`); everything else requires authentication —
  including in tests, which authenticate with real API keys via the
  `authenticated_client` / `admin_client` fixtures.
- **Config:** `app/config.py` / `.env` hold infrastructure only (DB, Redis,
  Celery, JWT). Business configuration lives in the `platform_settings` table,
  managed through the admin panel (`PlatformSettingsService`). Don't add
  business fields to `app/config.py`.
- **Migrations are additive-only.** Never DROP or RENAME in the same release —
  rollback restores container images, not schema.
- **Line length:** 100 chars in the backend (ruff-enforced).
- **Frontend:** Next.js App Router under `src/app/[locale]/`, all user-facing
  strings through next-intl (5 locales), no `React.FC`, no `any`, no inline
  `fetch` in components (use `src/lib/api.ts`).
- **Commits:** Conventional Commits — `feat(scope):`, `fix(scope):`,
  `test(scope):`.

## Testing philosophy

**If a test fails, fix the code, not the test.** Never weaken assertions, skip
tests, or disable auth to make a suite pass.

- Happy path + error/edge cases are both required.
- Auth surfaces: test 401, 403, expired tokens, missing headers.
- Financial code: test concurrency, idempotency, invalid amounts.
- Anything with locking needs a concurrent-access test.
- `# CONTRACT-TEST:` annotations mark invariant-encoding tests that must not
  be deleted in consolidation passes.

## API contract (frontend ↔ backend)

The FastAPI OpenAPI schema is the source of truth. After changing backend
schemas or routes:

```bash
python scripts/export_openapi.py     # writes openapi.json (no server needed)
cd frontend && npm run generate-types
```

CI fails if the committed `frontend/src/lib/generated/api.ts` drifts from the
backend schema. Never hand-edit generated files.

## Pull requests

1. Fork, branch from `main`, keep the diff focused.
2. Make sure `ruff check app/`, `ruff format --check app/`, `pytest`, and the
   frontend `lint` + `test` scripts all pass locally.
3. Describe **what** changed and **why** — link the issue if one exists.
4. CI (GitHub Actions) must be green: backend lint + tests vs real PostgreSQL,
   frontend lint + unit tests.

## Reporting bugs / requesting features

Use the issue templates. For security vulnerabilities, **do not open a public
issue** — see [SECURITY.md](SECURITY.md).
