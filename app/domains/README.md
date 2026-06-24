# `app/domains/` — Extracted Bounded Contexts

Each subdirectory here is one extracted bounded context from the modular monolith
migration (ADR-001). See `docs/BOUNDED_CONTEXTS.md` for the full map.

## Current residents

- **`solver/`** — BC1, extracted 2026-04-13 (Phase 3). Blueprint for future extractions.

Everything else still lives in flat `app/services/` and migrates here phase by phase.

## Extraction pattern (from the Solver migration)

Each extracted domain follows the same shape:

```
app/domains/<name>/
├── __init__.py        # Public surface of the domain
├── adapters/          # External integrations (solvers, APIs, third-parties)
├── models/            # SQLAlchemy ORM models owned by this domain
├── routes/            # FastAPI routers — imported by app/api/v2/router.py
├── schemas/           # Pydantic v2 request/response models
├── services/          # Business logic
└── tasks/             # Celery tasks for this domain
```

### Rules for new domain code

1. **Everything the domain owns lives under `app/domains/<name>/`.** Don't scatter into
   flat `app/services/`, `app/tasks/`, etc. once extraction is done.
2. **Cross-domain calls go through explicit interfaces.** Protocols + adapters for sync
   dependencies; fire-and-forget events for the rest. See
   `docs/BOUNDED_CONTEXTS.md` § "Cross-context call rules".
3. **`import-linter` contracts are law.** `pyproject.toml` lists 6 KEPT contracts. Never
   add an import that breaks them — extend the contract with justification instead.
4. **Migration preserves behavior.** When extracting a domain, use `sys.modules` shims so
   existing importers keep working. Zero-behavior-change is the acceptance criterion.

### When adding a new domain

1. Pick it from the extraction queue in `docs/BOUNDED_CONTEXTS.md` (the "Extracted?" column),
   or argue for a different order in a PR.
2. Create the 6-directory skeleton above.
3. Migrate services in one PR; keep shims in `app/services/` for one release, then drop.
4. Add an `import-linter` contract that forbids inbound imports from other domains
   except via the published interface.
5. Update `docs/BOUNDED_CONTEXTS.md` table (mark extracted).

### Why domains, not microservices

Modular monolith (ADR-001). One process, one DB, logical boundaries only. Splitting into
separate services is explicitly out of scope (modular monolith, ADR-001).
