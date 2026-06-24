# JAOT — Architecture Documentation

> Complete visual map of the system. Mermaid diagrams versioned in git, rendered natively on GitHub and in most markdown editors. Each file covers **one specific focus** to avoid overloading the view.

**Last updated:** 2026-04-18
**Source of truth for decisions:** [project roadmap](../../ROADMAP.md)
**Bounded contexts index:** [`docs/BOUNDED_CONTEXTS.md`](../BOUNDED_CONTEXTS.md)
**Identified technical debt:** [`TECH_DEBT.md`](./TECH_DEBT.md)

---

## Index

### 01 · Overview
High-level context: what JAOT is, who uses it, what stack it runs on.

- [`01-overview/01-system-context.md`](./01-overview/01-system-context.md) — C4 level 1 diagram (external context)
- [`01-overview/02-tech-stack.md`](./01-overview/02-tech-stack.md) — technologies and versions
- [`01-overview/03-bounded-contexts.md`](./01-overview/03-bounded-contexts.md) — summary of the 8 planned BCs

### 02 · Backend
FastAPI + SQLAlchemy + Celery. Layered architecture, Solver domain, and patterns.

- [`02-backend/01-layers.md`](./02-backend/01-layers.md) — request → service → DB/Celery layers
- [`02-backend/02-bounded-contexts.md`](./02-backend/02-bounded-contexts.md) — current state vs target of the modular monolith
- [`02-backend/03-domain-solver-uml.md`](./02-backend/03-domain-solver-uml.md) — UML of the `solver` domain
- [`02-backend/04-patterns.md`](./02-backend/04-patterns.md) — Protocol Adapter, FastAPI DI, Two-Tier Config, Queue Routing, Shim
- [`02-backend/05-import-linter.md`](./02-backend/05-import-linter.md) — the 6 contracts that protect boundaries
- [`02-backend/06-celery-flow.md`](./02-backend/06-celery-flow.md) — full sequence of an async solve

### 03 · Frontend
Next.js 16 App Router, i18n, shared state.

- [`03-frontend/01-app-router-map.md`](./03-frontend/01-app-router-map.md) — `[locale]/...` route map
- [`03-frontend/02-state-management.md`](./03-frontend/02-state-management.md) — contexts and hooks
- [`03-frontend/03-api-client.md`](./03-frontend/03-api-client.md) — HTTP client + refresh flow
- [`03-frontend/04-i18n-flow.md`](./03-frontend/04-i18n-flow.md) — next-intl and the 5 locales
- [`03-frontend/05-component-architecture.md`](./03-frontend/05-component-architecture.md) — component hierarchy

### 04 · Database
PostgreSQL + SQLAlchemy 2.0 + Alembic. Entities, multi-tenancy, migrations.

- [`04-database/01-erd-core.md`](./04-database/01-erd-core.md) — Identity + Model + Billing
- [`04-database/02-erd-marketplace.md`](./04-database/02-erd-marketplace.md) — Favorites, FeaturedPlacement, Ratings
- [`04-database/03-erd-automation.md`](./04-database/03-erd-automation.md) — Triggers + AI
- [`04-database/04-erd-platform.md`](./04-database/04-erd-platform.md) — PlatformSetting + AuditLog + Notification
- [`04-database/05-multi-tenancy.md`](./04-database/05-multi-tenancy.md) — how filtering by `organization_id` works
- [`04-database/06-migrations-flow.md`](./04-database/06-migrations-flow.md) — Alembic pipeline

### 05 · Infrastructure
Docker, the production host, Caddy, monitoring.

- [`05-infrastructure/01-docker-topology-prod.md`](./05-infrastructure/01-docker-topology-prod.md) — production topology
- [`05-infrastructure/02-docker-topology-dev.md`](./05-infrastructure/02-docker-topology-dev.md) — local stack
- [`05-infrastructure/03-monitoring-stack.md`](./05-infrastructure/03-monitoring-stack.md) — Prometheus + Grafana + Alertmanager
- [`05-infrastructure/04-network-ports.md`](./05-infrastructure/04-network-ports.md) — internal vs exposed ports
- [`05-infrastructure/05-celery-queue-workers.md`](./05-infrastructure/05-celery-queue-workers.md) — 3 queues / 3 workers post-Phase-6

### 06 · CI / CD
GitHub Actions: lint + tests on every push, deploy to a self-hosted runner on `main`.

- [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) — lint, backend + frontend tests
- [`.github/workflows/deploy.yml`](../../.github/workflows/deploy.yml) — build + deploy via self-hosted runner

### 07 · Use cases
Main flows as sequence diagrams.

- [`07-use-cases/01-signup-login.md`](./07-use-cases/01-signup-login.md) — signup, verification, login, refresh
- [`07-use-cases/02-solve-flow.md`](./07-use-cases/02-solve-flow.md) — solving a problem (the flagship flow)
- [`07-use-cases/03-create-model.md`](./07-use-cases/03-create-model.md) — builder with LLM assistant + RAG
- [`07-use-cases/04-marketplace-buy.md`](./07-use-cases/04-marketplace-buy.md) — template purchase (Stripe)
- [`07-use-cases/05-automation-trigger.md`](./07-use-cases/05-automation-trigger.md) — trigger/schedule runs a solve
- [`07-use-cases/06-admin-settings.md`](./07-use-cases/06-admin-settings.md) — admin modifies platform settings

### 08 · Architecture decisions (ADRs)
Index of documented decisions.

- [`08-decisions/README.md`](./08-decisions/README.md) — index of ADRs and phase decisions

---

## Conventions

- **Mermaid:** standard syntax (`classDiagram`, `sequenceDiagram`, `flowchart`, `erDiagram`). GitHub renders it natively.
- **Language:** titles and explanations in English; class, file, and function names exactly as they appear in the code.
- **Size:** no diagram has >25 nodes. If an area needs more, it is split into sibling diagrams.
- **Not exhaustive:** the truth lives in the code; these diagrams are an entry point. Notes include `path:line` references for navigation.

## How to maintain this documentation

1. When an extracted bounded context is added → update `02-backend/02-bounded-contexts.md`.
2. When the Docker topology changes → update `05-infrastructure/01-docker-topology-prod.md`.
3. When a new user flow is added → new file in `07-use-cases/`.
4. When an architecture decision is made → ADR in `08-decisions/` + link from this index.
5. Any technical debt detected → entry in `TECH_DEBT.md`.
