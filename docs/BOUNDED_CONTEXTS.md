# Bounded Contexts — Quick Reference

> Navigable index of the 8 bounded contexts in JAOT.
> This file is the authoritative day-to-day map of the 8 bounded contexts.
> The modular-monolith decision behind them is recorded in ADR-001.

## Context-at-a-glance

| BC | Role | Coupling | Where it lives today | Extracted? |
|---|---|---|---|---|
| **BC1: Solver** | Core | 2/5 | `app/domains/solver/` | ✅ Phase 3 (2026-04-13) |
| **BC2: Marketplace** | Core sub | 3/5 | `app/services/` (seller_analytics, featured_placement, verification, storage, template_scorecard), `app/api/v2/routes/models/` | ❌ Planned §6 |
| **BC3: Billing** | Core sub | 4/5 | `app/services/` (credits_service, stripe_service, stripe_connect, invoice, workspace_credits, reconciliation) | ❌ Planned §6 |
| **BC4: Identity** | Generic | 2/5 | `app/services/auth/`, `app/services/gdpr/`, User/Organization/APIKey/RefreshToken models | ❌ Planned §6 |
| **BC5: AI Assistant** | Supporting | 2/5 | `app/services/llm/`, `app/services/rag/`, document_extraction | ❌ Planned §6 |
| **BC6: Automation** | Supporting | 4/5 | `app/services/` (trigger, schedule, webhook, version), `app/tasks/` (trigger_tasks, webhook_tasks) | ❌ Planned §6 |
| **BC7: Observability** | Generic | 1/5 | `app/services/` (analytics, audit, notification) | ❌ Easiest extraction — pure leaf |
| **BC8: Platform Admin** | Generic | 1/5 | `app/services/settings_registry.py`, `app/services/platform_settings_service.py` | Stays in `app/shared/` permanently |

## When to work in which context

**Adding solver logic** → `app/domains/solver/` (adapters, services, routes, schemas, tasks all under this tree).

**Adding model catalog / marketplace features** → `app/api/v2/routes/models/` + `app/services/seller_*` / `featured_placement` / `template_scorecard`.

**Adding billing / Stripe / credits** → `app/services/credits_service.py`, `stripe_service.py`, `stripe_connect.py`.

**Adding auth / signup / API keys / GDPR** → `app/services/auth/`, `app/services/gdpr/`.

**Adding LLM / RAG / formulation assistant** → `app/services/llm/`, `app/services/rag/`.

**Adding triggers / schedules / webhooks** → `app/services/trigger_service.py`, `schedule_service.py`, `webhook_service.py`; async work in `app/tasks/trigger_tasks.py`, `webhook_tasks.py`.

**Adding analytics / audit logs / notifications** → `app/services/analytics_service.py`, `audit_service.py`, `notification_service.py`. Pure leaf — nothing else depends on it by design.

**Adding platform settings / feature flags** → `app/services/settings_registry.py` (defaults) + `PlatformSettingsService` (runtime). Never put business config in `app/config.py`.

## Cross-context call rules

Enforced by `lint-imports` (`pyproject.toml`). 6 KEPT contracts today.

**Allowed synchronous cross-context calls:**
- `solve_orchestrator` → `credits_service` (deduct / refund on solve)
- `trigger_tasks` → Solver + Credits (orchestrates solver runs)
- `featured_placement` → `credits_service` (deduct promotion fee)

**Everything else must be fire-and-forget:**
- Any context → `audit_service`, `analytics_service`, `notification_service` (leaf; no response contract)
- Any context → `PlatformSettingsService` (config read only)

**If you're about to add a direct import across contexts that isn't in the allowed list, stop.** Either use an existing async/event path, or extend the import-linter contract with justification. See `pyproject.toml` `[tool.importlinter]`.

## Extraction order (from §6)

The roadmap plans extractions in this sequence:

1. ✅ **Solver** (Phase 3, done) — first and hardest. 46 importers migrated via `sys.modules` shims. Blueprint for the rest.
2. **Observability** — pure leaf. Lowest risk. Good next extraction.
3. **AI Assistant** — already independent (PSS-only outbound). Low risk.
4. **Identity** — high fan-in (32+ importers). Breaks the Organization god model.
5. **Billing** — coupled to Organization. Depends on Identity extraction.
6. **Marketplace** — depends on Billing + Identity.
7. **Automation** — orchestrates 4 domains. Last.
8. **Platform Admin** — never extracted. Stays in `app/shared/`.

## Don't treat this as physical separation

This is a **modular monolith** (ADR-001). Contexts live in one Python package, one process, one database. The boundary is logical, enforced by:

- Directory layout (`app/domains/*/` when extracted)
- `import-linter` contracts
- Typed boundaries at the call sites (adapters, protocols)

Splitting into microservices is not planned and not desired; the boundary is logical only, enforced by the contracts above.
