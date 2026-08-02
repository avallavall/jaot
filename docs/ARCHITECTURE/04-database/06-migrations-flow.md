# Alembic Migrations Pipeline

> Incremental schema versioning. A DROP or RENAME is allowed when it is the right
> change (owner, 2026-08-02); what a rollback restores is the container image, not
> the schema, so an irreversible migration needs a backup taken before the deploy.

## CI/CD Flow

```mermaid
flowchart LR
    A["Developer changes a model<br/>app/models/optimization_model.py"] --> B["alembic revision --autogenerate<br/>-m 'add solver_name to executions'"]
    B --> C["Generates infra/alembic/versions/<br/>20260416_add_solver_name_to_executions.py"]
    C --> D["Review migration<br/>Verify there is no DROP/RENAME"]
    D --> E{"Is the change safe?"}
    E -->|NO| F["Reject + request fix<br/>e.g.: use RENAME with an alias"]
    E -->|YES| G["Commit migration file"]
    G --> H["CI: alembic upgrade head<br/>on test database"]
    H --> I{"Upgrade OK?"}
    I -->|NO| J["Fail CI + block merge<br/>Fix migration"]
    I -->|YES| K["Test suite runs<br/>against new schema"]
    K --> L["Merge to main"]
    L --> M["Deploy: alembic upgrade head<br/>on production DB"]
    M --> N["Schema updated"]
    
    N --> O["Rollback strategy:<br/>Container restart =<br/>prior image (prior schema)"]
```

## Current Migration Structure (64 total, single head)

```
infra/alembic/versions/
├── 20260305_add_locale_to_users.py
├── 20260311_add_conversation_attachments.py
├── 20260311_add_trigger_schedules.py
├── 20260314_add_model_media_columns.py
├── 20260314_add_platform_settings.py
├── 20260315_add_analytics_events.py
├── 20260315_add_seller_experience_tables.py
├── 20260317_add_credit_idempotency_constraint.py
├── 20260317_add_owner_fk.py
├── 20260317_add_platform_setting_audit.py
├── 20260322_financial_hardening_schema.py
├── 20260324_rename_enterprise_to_business.py  ← RENAME (historical — already ran; no current risk)
├── 20260326_add_credit_pools.py
├── 20260327_seed_platform_settings.py
├── ... (2026-04 → 2026-07: provenance, model projects, datasets, timestamptz, ...)
├── 20260712_p15_listings.py
├── 20260712_p15_backfill.py
├── 20260713_p15_view_events_project.py
├── 20260713_p15_reviews_favorites_project.py
├── ... (2026-07: conversation ledger, LLM v5 models, analysis cache, ...)
├── 20260726_index_unindexed_fks.py
├── 20260726_unlimit_plan_capacity.py
├── 20260726_listing_success_tallies.py
├── 20260727_instance_limits.py
└── 20260728_prune_orphan_settings.py  ← Latest
```

> Ask the tool rather than this list, which ages: `alembic -c infra/alembic.ini heads`
> must print exactly one head. Two means a branch that `upgrade head` will refuse.

> **Note (ADR-008):** the money/credit migrations in the history above (idempotency
> constraint, credit pools, financial hardening) built tables and columns that are now
> **dead** — the application no longer maps them. They stay in the chain untouched
> (kept for one release); a later release drops the schema.

### Last 5 Migrations

1. **20260728_prune_orphan_settings.py**
   - Deletes the 98 `platform_settings` rows no code reads (D-22): the `plan_*` tiers the
     instance profile replaced, ADR-008's billing keys, and the settings the 1.9 panel
     review retired. Data only — no schema touched, and `downgrade()` is a documented no-op

2. **20260727_instance_limits.py**
   - Collapses the four `plan_*` limit tiers into one `instance_*` profile, carrying across
     the value that restricts nobody so a seeded install keeps what its operator configured

3. **20260726_listing_success_tallies.py**
   - Adds the raw counters `success_rate` / `avg_execution_time_ms` are computed from —
     both had stayed NULL since the P1.5 fusion left them with no writer

4. **20260726_unlimit_plan_capacity.py**
   - Sets the per-plan capacity ceilings to `0` (unlimited) on already-seeded installs
     (D-21) — the 20260327 seed is `ON CONFLICT DO NOTHING`, so new registry defaults alone
     never reach them

5. **20260726_index_unindexed_fks.py**
   - Indexes 18 of the 23 unindexed foreign keys (D-14); the other 5 point at tables on the
     legacy DROP list or at ADR-008 orphans with no ORM model

## Conventions + Rules

### Additive-Only

```python
# ✓ ALLOWED:
def upgrade():
    op.add_column('model_executions', sa.Column('solver_name', sa.String()))
    op.create_index('ix_solver_name', 'model_executions', ['solver_name'])

# ✗ FORBIDDEN (in the same release):
def upgrade():
    op.drop_column('model_executions', 'solver_name')  # Breaks rollback → schema mismatch

# ✓ ALLOWED (with dual-write alias):
def upgrade():
    op.add_column('model_executions', sa.Column('solver_name_v2', sa.String()))
    # App writes to both during the transition
```

### ID Generation

```python
# Migrations NEVER generate IDs manually
def upgrade():
    op.add_column('users', sa.Column('id', sa.String(), nullable=False, primary_key=True))
    # Relies on app/shared/utils/id_generator.py:generate_id() in app code

# For backfill:
# 1. Migration: ADD COLUMN (nullable)
# 2. App code: backfill script using generate_id()
# 3. Follow-up migration: ALTER NOT NULL
```

### Migration Testing

```bash
# Local test:
alembic -c infra/alembic.ini downgrade -1  # Roll back the latest
alembic -c infra/alembic.ini upgrade head   # Reapply
pytest tests/migrations/ -v

# CI:
# 1. Fresh DB: psql jaot_test < schema_dump.sql
# 2. alembic upgrade head
# 3. ruff check + pytest
# 4. Merge if everything is OK
```

## Pre-Commit Checklist

- [ ] Migration generated by `autogenerate` (not manual)
- [ ] No DROP/RENAME without a fallback plan
- [ ] IDs are prefixed strings (generate_id)
- [ ] FK: ondelete="CASCADE" for org-scoped
- [ ] Indexes on (organization_id, created_at) for ranges
- [ ] Constraints named explicitly: `name='uq_X'`
- [ ] Timestamps: DEFAULT utcnow(), NOT NULL
- [ ] Migration tested on the test DB before merge

## Configuration Files

- `infra/alembic.ini` — Alembic config (DB connection string)
- `infra/alembic/env.py` — Script runner (autogenerate detection)
- `app/models/` — ORM definitions (source of truth)
