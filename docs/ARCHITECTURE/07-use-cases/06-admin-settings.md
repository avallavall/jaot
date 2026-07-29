# Use Case: Admin Platform Settings — Global Configuration

> Administration flow: an admin edits one of the 88 platform settings → the next request
> that reads it sees the new value.

## Diagram

```mermaid
sequenceDiagram
    participant Admin as Admin User
    participant Frontend as Frontend (/admin/settings)
    participant API as /api/v2/admin/settings/*
    participant PSS as PlatformSettingsService
    participant DB as PostgreSQL
    participant APIEndpoints as Other Endpoints (solve, signup, ...)

    note over Admin,API: --- VIEW SETTINGS ---
    Admin->>API: GET /admin/settings/registry
    API->>API: admin router dependency (get_admin_user)
    alt Not admin
        API->>Admin: 403 "Forbidden"
    end
    API->>Frontend: 200 {categories: {system: [...], limits: [...], solver: [...]}}

    Admin->>API: GET /admin/settings/values
    API->>PSS: get_all_values(db)
    PSS->>DB: SELECT * FROM platform_settings
    DB-->>PSS: rows
    PSS->>PSS: registry default for any key with no row; mask secrets as ****
    PSS-->>API: {key: {value, default_value, is_modified, source, ...}}
    API->>Frontend: 200 {settings}
    Frontend->>Frontend: Tabs grouped by operator task, built from the categories the API returned

    note over Admin,API: --- UPDATE SETTING ---
    Admin->>Frontend: Toggle "SOLVE_MAINTENANCE_MODE" ON
    Frontend->>API: PUT /admin/settings/values {updates: {SOLVE_MAINTENANCE_MODE: "true"}}
    API->>PSS: validate_value(key, value) against the registry constraints
    alt Validation fails
        API->>Frontend: 200 {updated: [], errors: {KEY: "reason"}}
    end
    API->>PSS: bulk_set(updates, changed_by)
    PSS->>DB: UPDATE platform_settings + INSERT platform_setting_audit
    API->>Frontend: 200 {updated: [keys], errors: {}}

    note over APIEndpoints,DB: --- RUNTIME EFFECT ---
    Client->>APIEndpoints: POST /api/v2/solve {problem}
    APIEndpoints->>PSS: get_bool(db, "SOLVE_MAINTENANCE_MODE")
    PSS->>DB: SELECT value FROM platform_settings WHERE key = ...
    PSS-->>APIEndpoints: "true"
    APIEndpoints->>Client: 503 + Retry-After

    note over Admin,API: --- AUDIT TRAIL ---
    Admin->>API: GET /admin/settings/audit
    API->>DB: SELECT * FROM platform_setting_audit ORDER BY changed_at DESC
    API->>Frontend: 200 {items, total, page, page_size}
```

## Critical Points

### Every setting is read by something

A setting that no code path reads is a control that does nothing when an operator turns
it. The 1.9 panel review removed 23 of those — dead keys plus keys the panel let an admin
edit while the runtime took the value from `.env` (`HOST`, `PORT`, `WORKERS`, `CELERY_*`,
`DATABASE_URL`). `tests/api/test_admin_settings.py` now fails if a registry entry has no
reader, and if any category has no settings. Read-only entries are exempt: they mirror a
code constant for display (`APP_VERSION`) and are refreshed at startup, so nothing can be
typed into them.

The check requires the key as a STRING. Matching the bare word let a Python constant of the
same name vouch for a setting nothing loads.

**Infrastructure stays in `.env`** (`app/config.py`): it is read before a database session
exists, so it cannot live in this table. The panel must not offer it.

### Categories (source of truth: `app/services/settings_registry.py`)

| Category | Examples | Panel tab |
|---|---|---|
| `system` | MAINTENANCE_MODE, SOLVE_MAINTENANCE_MODE, JAOT_DSL, HOME_ANNOUNCEMENT_* | Instance |
| `app` | APP_NAME, APP_VERSION (read-only) | Instance |
| `security` | REGISTRATION_ENABLED, JWT_*, AUTH_*_RATE_LIMIT_* | Access |
| `limits` | instance_max_variables, instance_max_daily_solves, instance_min_cron_interval_minutes, instance_allowed_features | Access |
| `solver` | SOLVER_DEFAULT_TIMEOUT, SENSITIVITY_*, IIS_* | Solver |
| `llm` | LLM_DEFAULT_MODEL, LLM_MONTHLY_BUDGET_EUR, LLM_THINKING_EFFORT | AI |
| `rag` | RAG_ENABLED, RAG_TOP_K, RAG_RERANKER_ENABLED | AI |
| `email` | EMAIL_BACKEND, SMTP_*, CONTACT_RECIPIENT | Email |
| `identifiers` | ID_PREFIX_*, API_KEY_DEFAULT_PREFIX | Advanced |
| `secrets` | JWT_SECRET, ANTHROPIC_API_KEY, SMTP_PASSWORD, STORAGE_* | Secrets |

Tabs are derived from the categories the registry API returns: a category no tab claims
falls into **Advanced** instead of disappearing. Before that, six categories — all of RAG
among them — had no tab at all and could only be changed with SQL.

### One limit profile, not four plan tiers

`limits` holds eight `instance_*` settings that apply to every organization.
`organizations.plan` survives as a label but no longer selects a different ceiling: the
four tiers were a leftover of the billing ADR-008 removed, and after D-21 relaxed the caps
they were identical apart from rate limits.

> **Every capacity limit accepts 0, which means unlimited**, and none has an upper bound:
> this is self-hosted software, and an operator with large hardware must be able to type
> any number. A rate limit of 0 allows all requests; it does *not* mean "no requests
> allowed". Any code comparing against one of these MUST check for 0 first — a plain
> `count >= limit` is true at zero and locks the instance out.

### Reads are not cached

`PlatformSettingsService` queries `platform_settings` on every read, with `get_many()` for
batches. A change takes effect on the next request — no invalidation step, and no stale
window. The fallback chain is DB row → registry `default_value` → `MissingSettingError`;
missing rows are also self-healed into the table at startup (`_ensure_settings_seeded`).

### Secrets

Masked as `****` in every response, and editable — a secret belongs in the registry only
if some code path reads it *through PSS*. `JWT_SECRET` takes precedence over the
environment, so rotating it from the panel signs every user out immediately; the editor
warns before saving.

### Audit trail

- `PlatformSettingAudit`: one immutable row per change, with old value, new value, actor.
- Reset writes the registry default back (the row always exists for future reads).
- Read-only keys and unchanged values are skipped, so they never produce audit noise.

### Permission check

Every endpoint sits under the admin router's `get_admin_user` dependency —
non-admins get 403.

## Relevant Files

- `app/api/v2/routes/admin/settings.py` — registry / values / reset / audit endpoints
- `app/services/platform_settings_service.py` — typed accessors, validation, audit
- `app/services/settings_registry.py` — the settings that exist and their constraints
- `app/models/platform_setting.py`, `app/models/platform_setting_audit.py`
- `frontend/src/app/[locale]/admin/settings/page.tsx` — tab grouping
- `app/config.py` — infrastructure only, never business config
