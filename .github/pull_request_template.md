## What & why

<!-- What changes, and what problem it solves. Link the issue if one exists. -->

## Checklist

- [ ] `ruff check app/` and `ruff format --check app/` pass
- [ ] `pytest` passes (tests run against real PostgreSQL — no DB mocks)
- [ ] `cd frontend && npm run lint && npm run test` pass (if frontend touched)
- [ ] OpenAPI types regenerated if backend schemas changed (`scripts/export_openapi.py` + `npm run generate-types`)
- [ ] Migration is additive-only (no DROP/RENAME in the same release)
