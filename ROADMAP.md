# Roadmap

JAOT is maintained best-effort (monthly issue triage, quarterly dependency/CVE
pass). This roadmap is intentionally small and honest — it lists work the
maintainer actually intends to do, plus areas where contributions would have
outsized impact.

## Now (shipped and working)

- Solver-agnostic core with **SCIP** and **HiGHS** adapters behind a
  `SolverAdapter` protocol; per-solver Celery queues and workers
- Optional **Hexaly** adapter (bring your own license,
  `requirements-hexaly.txt`)
- **102 optimization templates across 34 YAML files** + **27 problem-data generators**
  (knapsack, VRP, scheduling, production planning, portfolio, MDPDP, …)
- **LLM formulation assistant** (Anthropic Claude) with RAG over the template
  library (Qdrant + local sentence-transformers), document context (PDF/CSV/TXT),
  real token-cost tracking and a monthly budget guardrail with auto-pause
- **Marketplace** for sharing models (credits-based; Stripe is optional
  BYO-keys and code-complete but never exercised against live Stripe)
- **MCP server** exposing solver tools to AI agents
- Multi-tenant auth (API keys + JWT), credits ledger, admin panel with
  runtime platform settings, i18n (en/es/ca/fr/de), Prometheus/Grafana/
  Alertmanager monitoring stack

## Next (maintainer's short list)

- First-run experience: `docker compose up` → seeded admin + org with starting
  credits, zero manual SQL
- Documentation pass: all architecture docs in English, contributor-grade
  QUICKSTART, cold-start validated on a clean machine (<30 min to first solve)
- Demo hardening: abuse limits and budget alerts for the public instance

## Help wanted (great contribution targets)

- **Replace Qdrant with pgvector** — the RAG index is 186 documents; a
  dedicated vector DB is overkill. Migrating to pgvector would remove one
  service from the compose stack. Self-contained, well-scoped.
- **More solver adapters** — OR-Tools (CP-SAT), CBC, or GLPK behind the
  existing `SolverAdapter` protocol (`app/domains/solver/adapters/`). The
  HiGHS adapter is a good reference implementation.
- **mypy strict burn-down** — the repo declares strict mode; ~150 errors
  remain. Mechanical but valuable; would add type-checking to public CI.
- **VRP time-window constraints** — most-requested template extension.
- **More import/export formats** — LP/MPS coverage exists; AMPL/GMPL or
  solver-specific tuning parameter pass-through are natural extensions.
- **New templates and generators** — domain expertise welcome (energy,
  healthcare, logistics).

## Non-goals

- Becoming a hosted SaaS — this is a self-hostable platform; jaot.io is a demo
- Cloud-provider-specific deployment tooling (the reference deploy is a single
  server with Docker Compose)
- Royalties, dual licensing, or feature gating — everything is Apache-2.0
