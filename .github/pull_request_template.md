## What & why

<!-- What changes, and what problem it solves. Link the issue if one exists. -->

## Checklist

- [ ] `ruff check` and `ruff format --check` pass over `app/ infra/ scripts/ deploy/ tests/`
- [ ] `pytest` passes (tests run against real PostgreSQL — no DB mocks)
- [ ] `cd frontend && npm run lint && npm run test` pass (if frontend touched)
- [ ] OpenAPI types regenerated if backend schemas changed (`scripts/export_openapi.py` + `npm run generate-types`)
- [ ] Migration has a working `downgrade()`; if it cannot be reversed, the PR says so and names the backup to take before deploying (a rollback restores the image, not the schema)
