# Changelog

All notable changes to JAOT are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) — Semantic Versioning.

---

## [Unreleased]

### Added

- **BYOK — per-organization Anthropic API key (2026-06-26)** — An organization can store its **own** Anthropic API key and run all AI features on its own account. Resolution is **BYOK-first**: if an org has a key, every LLM call (chat, solution explainer, infeasibility explainer) runs on *their* account — **no JAOT credits charged**, the platform monthly-budget guardrail (`LLM_MONTHLY_BUDGET_EUR`) is bypassed, and no platform `cost_eur` is recorded. Orgs without a key fall back to the shared platform key, still budget-gated. The key is **Fernet-encrypted at rest** (derived from `JWT_SECRET`, no new env var), never returned in plaintext (only a masked hint to the owner) and never logged. New owner-only endpoints `GET/PUT/DELETE /api/v2/organization/anthropic-key`; the streaming generators now accept a resolved client (`app/services/llm/byok.py`). Frontend: an "Your own Anthropic API key" panel in workspace settings + a discoverability nudge in the AI surfaces (builder chat + result-page explainers), 5-locale i18n. Additive migration `20260626_org_anthropic_key` (one nullable column).
- **Infeasibility explainer — IIS + AI (P2, 2026-06-26)** — When a solve returns INFEASIBLE, stop leaving the user stranded. JAOT now computes a minimal conflicting set (an **Irreducible Infeasible Set**) by **deletion filtering** — solver-agnostically, in `app/domains/solver/services/infeasibility.py` (`compute_iis`), which only re-solves candidate `OptimizationProblem`s as pure feasibility checks and never touches a solver's native API (import-linter contract 5 stays green). It identifies the exact conflicting constraints *and* variable bounds (`conflict_type`: constraint/bound/mixed), bounded by two new platform settings — `IIS_MAX_CONSTRAINTS` (150) and `IIS_TIME_BUDGET_SECONDS` (20) — falling back to a clearly-flagged heuristic (`method="llm_only"`) when exceeded. New additive schema `InfeasibilityAnalysis` (persisted into `result_data` via `OptimizationResult.to_result_data`). On-demand endpoint `POST /api/v2/solve/{execution_id}/infeasibility-analysis` (org-scoped; the O(n)-solve cost is paid only when asked). New LLM capability `explain_infeasibility` + endpoint `POST /api/v2/llm/conversations/{id}/explain-infeasibility` streams a plain-language explanation grounded in the IIS (or a flagged heuristic when none), reusing the chat budget + pre-paid-credit + cost-tracking pipeline (reuses the `EXPLAINING` status code — no new event codes). Frontend: a "Why is this infeasible?" panel on the execution result page that highlights the conflicting constraints and streams the fix (5-locale i18n). Reuses P1's explainer infrastructure.
- **Solution explainer + sensitivity analysis (P1, 2026-06-26)** — After a solve, understand it. Sensitivity is extended solver-agnostically: per-constraint **shadow prices** + binding flags (already present) now joined by per-variable **reduced costs** and at-bound flags, exact for pure LP and approximate (LP-relaxation) for MIP; objective/RHS ranging is surfaced only when the solver exposes it (never fabricated). Sensitivity is now persisted into `ModelExecution.result_data` so it reaches the result page. New LLM capability `explain_solution` + endpoint `POST /api/v2/llm/conversations/{id}/explain-solution` streams a **plain-language explanation** grounded strictly in the actual formulation/solution/sensitivity, reusing the chat budget + pre-paid-credit + cost-tracking pipeline (new `EXPLAINING` status code). Frontend: a "Explain this solution" panel on the execution result page + a variable-reduced-costs table in the Sensitivity tab (5-locale i18n).
- **SolverAdapter Protocol (Phase 4, v2.2, 2026-04-14)** — Solver-agnostic abstraction shipped. New `app/domains/solver/adapters/` layer: `SolverAdapter` typing.Protocol + frozen `SolverCapabilities` dataclass (9 fields) + `SolverRegistry` singleton + exception hierarchy (`SolverError`, `SolverNotFoundError`, `SolverUnavailableError`) + `MultiObjectiveSolverAdapter` extension. `SCIPAdapter` owns the full SCIP pipeline (12 private methods + event handler). `register_default_adapters()` wired into `create_app()` before route registration (explicit per D-09, no decorator auto-registration). 6 import-linter contracts enforce the boundary (`solver-services-no-pyscipopt` keeps pyscipopt inside adapters/ only)
- **Solver domain extraction (Phase 3, v2.2, 2026-04-13)** — First bounded context extracted to `app/domains/solver/` per modular monolith plan (ADR-004). 38 files moved (services, models, schemas, routes, tasks, generators); 46 importers preserved via sys.modules shims at the old `app/services/solver/*` paths. Zero behavior change. `solver-domain-no-shim-imports` contract enforces canonical import paths for new code
- **Modular monolith foundation (Phase 2, v2.2, 2026-04-10)** — `app/domains/` and `app/shared/` directory structure. `deps.py`, `utils/`, `constants/` moved to shared/ with re-export shims. `import-linter` installed with 5 initial contracts (app/→tests/, test subdirs independent, app/shared/→no domain imports, domain isolation, canonical paths)
- **RAG system** — Qdrant vector DB + sentence-transformers (`BAAI/bge-small-en-v1.5`, 384-dim, local CPU); 186 docs indexed; hybrid search with BM25 + dense retrieval; `RAG_ENABLED=true` in production
- **File Import/Export (P5)** — 6 export formats (MPS, LP, CIP, SOL, CSV, JSON); drag-and-drop file import; solve analytics dashboard with variable chart and auto-insights
- **Template system overhaul (P2)** — 102 templates in 34 unified YAML files, 27 problem generators; template visibility bug fixed
- **MDPDP generator** — Multi-Depot Pickup-and-Delivery with Time Windows and Tachograph constraints
- **Monitoring alerts** — 24 alert rules across 7 groups; Resend SMTP for email alerts
- **CI pipeline** — lint, test, deploy stages; replaced manual deployment
- **LLM stable error codes** — raw error strings replaced with i18n-mapped codes in LLM-to-Solve bridge
- **Idempotency hardening** — `Idempotency-Key` now bound to request body hash

### Changed

- **Marketplace desmonetized → free & collaborative (2026-06-25)** — New `MONETIZATION_ENABLED` platform setting (default **off**) gates every paid feature. With it off: marketplace activation is free (no commission, no self-purchase block), publishing forces the price to 0, and seller earnings/payouts, credit withdrawals/top-ups, Stripe Connect onboarding, featured-placement purchases, billing checkout, and the public `/pricing` endpoint all respond 404. Credits become a pure usage quota. The frontend drops the For Sellers landing, the billing page, the seller earnings dashboard, all price UI, and the price/free filters; copy across all 5 locales shifts from buy/sell/earn/90% to use/share/publish/community. The paid code is dormant and reversible — a self-hosted deployment can flip the flag on ("bring-your-own Stripe"). No schema changes (additive-only).
- **solver_service.py reduced 949 → 348 lines (-66%, Phase 4)** — rewritten as solver-agnostic orchestrator. All SCIP-specific code moved to `app/domains/solver/adapters/scip.py`. Dispatches solve() calls via `registry.get(solver_name).solve()`. Multi-objective loops (`_solve_weighted`, `_solve_epsilon_constraint`) build fresh `OptimizationProblem` subproblems and call `adapter.solve()` — never touch SCIP API directly. Closes TD-2 (partial — auth/stripe/credits still >800L) and TD-3 (expression_parser pyscipopt-free)
- **model_builder.py and file_import.py converted to sys.modules shims (Phase 4)** — bodies absorbed into `app/domains/solver/adapters/_scip_model_builder.py` and `_scip_import.py`. Old module paths continue working via lazy `__getattr__` in package init; 46 existing importers + `tests/test_file_import.py` + `tests/test_file_export.py` unchanged
- **file_export.py canonical import (Phase 4, Pitfall 1)** — `from app.domains.solver.adapters._scip_model_builder import build_scip_model` (fully-qualified, no ambiguity)
- **Platform cleanup (P4)** — dashboard improvements, navigation simplification; Featurebase removed, replaced with GitHub Issues feedback (repository issues)
- **Architecture** — Modular monolith decision (ADR-004), feature-led domain extraction planned; P3 multi-solver as first bounded context
- **Documentation consolidated** — from 31 to 11 files; strategic roadmap as single source of truth
- **Test suite audit** — dead/chapuza tests removed, weak assertions strengthened, missing tenant/concurrency/idempotency coverage added across auth, solver, billing, templates, and API modules

### Fixed

- File import JSON depth check (pre-parse instead of `RecursionError`)
- 15 missing i18n keys added to es, ca, fr, de locales
- PDF export blank tab, post-import redirect to execution detail
- Export 401 auth error
- Race condition in P5 import/export flow
- Generic `pytest.raises(Exception)` replaced with typed exceptions

---

## [2.8.0] - 2026-02-19

### Invoices, SLA, Health Monitoring

### Added

- **Invoice system** — automatic invoice generation for subscriptions and credit top-ups; `Invoice` model with line items (JSON), totals, tax, Stripe refs; HTML rendering for print-to-PDF; `GET /billing/invoices`, `GET /billing/invoices/{id}`, `GET /billing/invoices/{id}/html`; 35 tests
- **SLA document** — `docs/operations/SLA.md` with uptime targets (99.0%–99.95%), service credits, incident response times, rate limits, data retention, support tiers
- **Health status endpoint** — `GET /api/v2/health/status` with component checks (database connectivity + latency, SCIP solver, memory, disk); returns healthy/degraded/down status for SLA monitoring
- **Alembic migration** — `invoices` table with indexes on `invoice_number` and `organization_id`

### Changed

- `ROADMAP.md` — Milestone 2 fully complete (invoice generation, SLA commitment checked off)
- `CLAUDE.md` — added Invoice System, SLA & Health Monitoring sections; updated test count to 461
- `API REFERENCE.md` — added invoice endpoints documentation

---

## [2.7.0] - 2026-02-19

### Billing, Templates, Deployment & Testing

### Added

- **Stripe billing integration** — subscription checkout, credit top-up purchases, webhook processing, billing portal; `app/services/stripe_service.py`, `app/api/v2/billing.py`; Organization model extended with `stripe_customer_id` and `stripe_subscription_id`
- **4 new model templates** — Employee Scheduling (shift coverage, unavailability, min/max hours), Vehicle Routing / CVRP (MTZ subtour elimination, capacity constraints), Portfolio Optimization (linear Markowitz with cardinality and sector constraints), Bin Packing (symmetry breaking, capacity constraints)
- **Public credit calculator** — `POST /api/v2/credits/calculator` (no auth required); estimates credits based on problem complexity with cost-by-plan breakdown
- **Production deployment config** — `docker-compose.prod.yml` with production server tuning, Caddy TLS, json-file logging, `.env.production` template
- **91 new backend tests** — `test_template_engine.py` (46 tests: all 10 generators, edge cases, sanitization), `test_billing.py` (24 tests: Stripe service, endpoints, webhooks), `test_credit_calculator.py` (21 tests: formula, validation, edge cases)

- **Onboarding email sequence** — 5-email drip campaign (Day 0, 1, 3, 7, 14); pluggable email service with console/SMTP backends; Celery tasks with retry; triggered on signup
- **Email service abstraction** — `app/services/email_service.py` with `ConsoleBackend` (dev) and `SMTPBackend` (prod)
- **PostgreSQL test infrastructure** — tests run against real PostgreSQL (`jaot_test` database); 23 PG-specific tests (schema, constraints, JSON, Alembic, Stripe)
- **Alembic migrations** — full infrastructure, initial migration for all 15 tables, upgrade/downgrade tested
- **Python SDK** — initial `JAOT` client package (internal, not published); `sdk/` package with `JAOT` client, solve (template + raw), model catalog, credits, error handling with retries; 33 tests
- **38 onboarding email tests** + **33 SDK tests**

### Changed

- Dockerfile healthcheck URL fixed from `/api/v1/health` to `/api/v2/health`
- Landing page pricing corrected to match platform settings (Free: 50 credits, Starter: €19/600 credits, Pro: €49/2,500 credits, Business: €149/20,000 credits)
- `stripe>=8.0.0` and `alembic>=1.18.0` added to `requirements.txt`
- Stripe and email env vars added to `app/config.py` and `.env.example`
- Billing webhook and credit calculator added to public endpoints in auth middleware
- `seed_models.py` updated to feature new templates in marketplace
- `app/db/base.py` refactored: lazy import of `SessionLocal` in `get_db()`
- `TESTING_GUIDE.md` rewritten in English with full coverage of new features
- `ROADMAP.md`, `BUSINESS_PLAN.md` §9, `API REFERENCE.md` updated to reflect current state

### Fixed

- Landing page plan data inconsistency (was showing €99/10K for Pro instead of €79/5K)

---

## [2.6.0] - 2026-02-19

### Notifications + Documentation

### Added

- **Notification system** — in-app notifications for execution events (job queued, completed, failed); `Notification` model with read/unread state; REST endpoints at `/api/v2/notifications`
- **Full developer documentation** — QUICKSTART, CONTRIBUTING, SOLVER internals, API Reference (all endpoints with JSON examples), AUTHENTICATION, WEBSOCKETS, ADRs for SCIP, RabbitMQ/Celery, and multi-tenancy

### Changed

- Documentation restructured from flat files into `docs/getting-started/`, `docs/api/`, `docs/development/`, `docs/ARCHITECTURE/decisions/`, `docs/product/`
- Roadmap switched from version-based to milestone-based format
- README rewritten as a concise landing page with 3-line quickstart

---

## [2.5.0] - 2025-12-11

### Refactoring — Modular Architecture (v2.5)

A multi-phase internal refactor to improve maintainability without changing external behaviour.

### Changed

- **Solutions → Models rename** — all internal and external references updated (backend, frontend, DB schema, Celery tasks, tests)
- **Modular routers** — `models.py` (2 000+ lines) split into focused sub-modules under `app/api/v2/routes/models/`
- **Modular admin** — `admin.py` split into modular structure under `app/api/v2/routes/admin/`
- **Modular profiles** — `profiles.py` extracted into `app/api/v2/routes/profiles/`
- **Shared schemas** — common Pydantic schemas extracted into `app/schemas/` to eliminate duplication across `auth.py`, `keys.py`, and other routes
- **Shared utilities** — `app/utils/` now contains `id_generator`, `pagination`, `datetime_helpers`, `validators`, `slug`
- Base currency changed from USD to EUR
- All pytest deprecation warnings resolved

### Fixed

- `init_db.py` updated to include all models (`ModelReview`, `UserFavorite`, `RecentModel`)
- Admin endpoints no longer matched by public path patterns (auth bypass bug)
- Sidebar UX and public profile endpoints

---

## [2.1.0] - 2025-12-09

### Async Execution + Marketplace

### Added

- **Async execution** — jobs submitted to RabbitMQ queue, processed by Celery workers
- **WebSockets** — real-time execution monitoring; convergence graph events streamed to the frontend
- **Publish to marketplace** — model authors can publish solutions from the UI
- **Marketplace profiles and reviews** — author public profiles, star ratings, review text
- **Verification system** — badge management and organization verification
- **Favorites** — users can bookmark models; `UserFavorite` and `RecentModel` tracking
- **Execution validation** — input payload validation before job submission
- **Cancel / rerun** — cancel queued executions; rerun with same payload
- **Solutions management page** in admin dashboard

### Changed

- Frontend icons migrated from emoji to Lucide React
- `/settings` renamed to `/workspace`

### Fixed

- Hydration error in Next.js SSR
- Default `Code` icon for custom solutions without a category
- SolverService used in Celery tasks (was incorrectly using `UniversalSolver`)
- Re-activation of already-activated solutions prevented

---

## [2.0.0] - 2025-12-09

### Major Release — Complete V2 Architecture

Full rewrite of the platform. Plugin-based system replaced by a universal solver architecture.

### Added

- **Universal SCIP solver** — single `/api/v2/solve` endpoint for all LP/MIP problems
- **Model Catalog** — browse and activate pre-built optimization solutions
- **My Models** — per-organization model activation and management
- **Execution history** — full audit trail with timing, status, and credit usage
- **Credits system v2** — multi-currency (EUR, USD, GBP, CHF), earned credits, scheduled withdrawals
- **Withdrawal system** — request and schedule credit withdrawals
- **Modern React frontend** — Next.js 15, TypeScript, Tailwind CSS, shadcn/ui components
- **Admin dashboard** — comprehensive organization, user, model, and credit management
- **API v2** — complete REST API at `/api/v2/` with OpenAPI docs
- **Health & metrics** — `/api/v2/health` endpoint with system metrics
- **Docker Compose** — multi-service orchestration (API, Celery, PostgreSQL, RabbitMQ, Ollama, frontend)
- **Pagination** — all list endpoints return `PaginatedResponse[T]`
- **Rate limiting** — per-plan rate limits on solve endpoint
- **Multi-tenant auth** — SHA-256 hashed API keys; auth always enabled on all endpoints

### Removed

- Plugin system
- AI Builder (will return as AI Model Builder in a future milestone)
- Wizard (replaced by model templates)
- API v1
- Legacy HTML/JS/CSS dashboard
- Static frontend

### Changed

- PostgreSQL as exclusive database (SQLite removed from production path)
- Authentication simplified to API key only (no session cookies)
- Docker setup consolidated into a single `docker-compose.yml`

---

## [1.5.0] - 2025-11-27

### GenAI Factory + Sandbox

### Added

- **GenAI Factory** — AI-powered model generation using local Ollama backend (migrated from Claude/GPT)
- **Secure sandbox execution** — process isolation and resource limits for user-submitted code
- **Wizard v2** — variable-based JSON generation for model configuration
- **Admin metrics dashboard** — builder stats and enhanced user management
- **Admin filtering** — filter users and organizations in admin panel
- **Organization deletion** — admin can delete organizations and their data
- **Credit tracking** — admin user tracked in credit addition events

---

## [1.4.0] - 2025-11-25

### Pagination + Admin Improvements

### Added

- Pagination on API keys, usage history, and admin activity endpoints
- Loading indicators for dashboard actions
- Shared utilities for API, UI, and pagination across frontend components

### Changed

- Admin and dashboard scripts refactored to use shared utilities
- Common UI component styles extracted into `vintage-theme.css`

---

## [1.3.0] - 2025-11-23

### Admin Dashboard Redesign

### Added

- Comprehensive admin dashboard with vintage theme styling
- User management: view, suspend, delete users
- Organization management: view credits, usage, API keys

### Changed

- GenAI Builder migrated from Claude/GPT to local Ollama backend (no external API costs)

---

## [1.2.0] - 2025-11-19

### GenAI Factory MVP

### Added

- GenAI Factory MVP: generate optimization models from natural language using Claude Sonnet + GPT fallback
- Database models for GenAI Factory (`GeneratedModel`, `GenerationRequest`)
- Type safety improvements in credits service

---

## [1.1.0] - 2025-11-18

### Analytics + Vintage Theme

### Added

- Time-series analytics: credit usage over time, execution trends
- Granular analytics: problem type breakdowns, constraint complexity distribution
- Usage analytics dashboard in the frontend
- End-to-end auth journey tests for the solve endpoint
- Comprehensive test suite for logistics module

### Changed

- UI redesigned with vintage/retro theme styling
- Real auth middleware used in admin tests (replaced mocks)

---

## [1.0.0] - 2025-11-13

### Initial Release

- Plugin-based optimization system with PySCIPOpt backend
- Multi-tenant architecture with organization scoping
- Credit system with Free/Pro/Enterprise plans
- AI Builder for plugin generation
- Admin dashboard (HTML/JS)
- API key authentication
- PostgreSQL database
- Docker Compose setup
- Comprehensive test suite and load testing infrastructure

---

## Notes

- v1.x used a plugin architecture that has been fully replaced in v2.
- Fresh database recommended when upgrading from v1 to v2 (schema is not compatible).
- Dates reflect when changes were merged to `main`.
