# Architecture Overview — JAOT

> **Updated:** July 2026
> **Architecture:** Modular Monolith (see [Architecture Decision Records](#architecture-decision-records) below)

## Overview

JAOT is a multi-tenant optimization-as-a-service platform. Users build, share, and automate optimization models via API, the model studio, or AI assistant. Single deployable monolith evolving toward modular monolith with domain-bounded contexts.

```
┌──────────────────────────────────────────────────────────┐
│                      FRONTEND                             │
│                Next.js 16 (React 19)                      │
│           5 locales (en, es, ca, fr, de)                  │
│                    localhost:3000                          │
└────────────────────────┬─────────────────────────────────┘
                         │ HTTP/REST + SSE + WebSocket
┌────────────────────────▼─────────────────────────────────┐
│                      BACKEND                              │
│               FastAPI (Python 3.12)                       │
│               4 Uvicorn workers                           │
│                    localhost:8001                          │
│  ┌────────┬────────┬────────┬────────┬────────┬───────┐  │
│  │ Auth   │ Solver │ LLM/   │ Model  │Market- │Trigger│  │
│  │  ASGI  │Pipeline│  RAG   │Projects│ place  │Service│  │
│  │Middlew.│(async) │        │(studio)│        │       │  │
│  └────────┴────────┴────────┴────────┴────────┴───────┘  │
└──┬───────────┬───────────┬───────────┬───────────┬───────┘
   │           │           │           │           │
┌──▼──┐  ┌─────▼─────┐ ┌──▼──┐  ┌─────▼─────┐ ┌──▼────┐
│Post-│  │ RabbitMQ  │ │Redis│  │  Qdrant   │ │Anthro-│
│greSQL│  │ + Celery  │ │     │  │(RAG vecs) │ │pic API│
│ 18  │  │  workers  │ │     │  │           │ │Claude │
└─────┘  └───────────┘ └─────┘  └───────────┘ └───────┘
```

## API Structure

```
/api/v2/
├── auth/              # Email signup/login, JWT, refresh, password reset
├── solve/             # Direct solve, templates, file import/export, insights, analytics
├── models/            # Public marketplace catalog (listings), executions, favorites, media
├── llm/               # AI formulation assistant (SSE streaming)
├── builder/           # Visual model builder documents
├── projects/          # ModelProject (studio): versions, stats, datasets, solve, publish, from-template/from-marketplace
├── author/            # Author analytics (views, adoption of published models)
├── keys/              # API key management
├── triggers/          # Automated solve triggers + cron schedules
├── notifications/     # In-app notifications + preferences
├── workspaces/        # Workspace management, members, invites, audit
├── profiles/          # User/org public profiles, reviews
├── gdpr/              # Data export, account deletion
├── admin/             # Users, orgs, models, settings, analytics, marketplace
├── health/            # Health check
├── metrics/           # Prometheus metrics
├── mcp/               # MCP server (Model Context Protocol)
└── ws/                # WebSocket (solve progress streaming)
```

## Key Pages (Frontend)

| Route | Purpose |
|---|---|
| `/studio` | My Models — every model is a versioned `ModelProject` |
| `/studio/new` | Launcher: canvas, AI assistant, JSON editor, import, template, marketplace |
| `/studio/templates` | Template gallery (seeds a project from a curated template) |
| `/studio/{id}/build` | Workspace — Build tab (Canvas / Assistant / Editor / JModel lenses) |
| `/studio/{id}/analyze` | Workspace — Analyze tab (stats, health, explain, I/O, publish entry) |
| `/studio/{id}/solve` | Workspace — Solve tab (async solve, live progress, per-project history) |
| `/studio/{id}/publish` | Publish a committed version to the marketplace |
| `/solve` | Redirects to `/studio` (legacy "Activated Models" collapsed by the P1.5 fusion) |
| `/solve/executions` | Global execution history (all models, org-wide) |
| `/solve/analytics` | Solve analytics dashboard |
| `/solve/favorites` | Favorite marketplace models |
| `/solve/import` | File import (MPS/LP/CIP/JSON) |
| `/solve/multi-objective` | Multi-objective optimization |
| `/builder` | Visual model builder (canvas substrate) |
| `/builder/ai-assistant` | AI formulation assistant |
| `/builder/templates` | Template gallery |
| `/marketplace` | Model marketplace (listings; one action: "Use in studio") |
| `/marketplace/authors/{orgId}` | Public author profile |
| `/triggers` | Automated triggers |
| `/workspace` | Dashboard, API keys, settings |
| `/admin` | Admin panel |

## Authentication

- **API Keys**: Prefixed (`ok_live_`, `ok_test_`), SHA-256 hashed, per-organization
- **JWT**: Email/password login with access + refresh tokens (HttpOnly cookies)
- **Auth Middleware**: Pure ASGI middleware (not BaseHTTPMiddleware), validates every request
- **Auth is always enabled** — no bypass flag. Every endpoint protected unless in `PUBLIC_PATHS`

## Multi-Tenancy

Shared database with `organization_id` column scoping. Every query filtered by `org.id` via `CurrentOrg` dependency injection.

## Solver

Solver-agnostic abstraction via **SolverAdapter Protocol** (shipped Phase 4, v2.2). Currently ships SCIP (via PySCIPOpt), HiGHS (via highspy), and CBC and GLPK as command-line programs the adapter runs as separate processes, plus an optional Hexaly adapter (proprietary SDK, bring-your-own-license). New solvers are added by implementing a single adapter behind the protocol.

Architecture (`app/domains/solver/`):
- **`adapters/base.py`** — `SolverAdapter` Protocol (`solve`, `is_available`, `validate_license`), `SolverCapabilities` frozen dataclass (9 fields), exception hierarchy (`SolverError`, `SolverNotFoundError`, `SolverUnavailableError`), `MultiObjectiveSolverAdapter` extension
- **`adapters/registry.py`** — `SolverRegistry` singleton (`register`, `get`, `list_available`, `reset`). Name normalization via `.lower()`
- **`adapters/scip.py`** — `SCIPAdapter` owns the full SCIP pipeline (12 private methods: `_configure_solver`, `_create_variables`, `_add_constraints`, `_set_objective`, `_apply_warm_start`, `_extract_result`, `_extract_sensitivity`, `_extract_sensitivity_for_mip`, `_has_integer_variables`, `_map_status`, `_build_model`, `_finalize_progress_history`)
- **`adapters/_scip_expression.py`**, **`_scip_import.py`**, **`_scip_model_builder.py`** — private helpers with lazy pyscipopt imports
- **`services/solver_service.py`** (348 lines) — thin solver-agnostic orchestrator; dispatches through `registry.get(solver_name).solve()`. Multi-objective loops (`_solve_weighted`, `_solve_epsilon_constraint`) build fresh `OptimizationProblem` subproblems and call `adapter.solve()` — never touch SCIP API directly
- **`services/model_builder.py`**, **`services/file_import.py`** — sys.modules shims redirecting to adapter-side helpers (preserves 46 existing importers)
- **Bootstrap**: `register_default_adapters()` called from `create_app()` before route registration (no decorator auto-registration; explicit for supply-chain safety per ADR D-09)

Supporting components:
- **31 problem generators** in `app/domains/solver/services/generators/` — produce solver-agnostic `OptimizationProblem`
- **Expression parser** (`app/domains/solver/services/expression_parser.py`) — recursive descent, produces `ParsedExpression` IR. Imports without pyscipopt (TD-3 closed in Phase 4)
- **Template engine** — dispatches to generators based on template category
- **Async solve pipeline** (ADR-007) — every entry point enqueues the same `solve_async` Celery task; `execution_writer` is the single ModelExecution writer (the `solve_orchestrator.py` module survives only as a helper home: `validate_problem`, `ExecutionSource`, warm-start loading)
- **File import/export** — MPS, LP, CIP, JSON upload; MPS, LP, CIP, SOL, CSV, JSON download

Import boundary enforced by `pyproject.toml` [tool.importlinter] contract `solver-services-no-pyscipopt`: any `from pyscipopt` outside `app/domains/solver/adapters/` fails CI (6/6 contracts KEPT).

## Async Tasks (Celery)

Broker: RabbitMQ. Task modules:
- `solve_tasks` — async solver execution
- `trigger_tasks` — triggered solve execution
- `email_tasks` — onboarding email sequence
- `webhook_tasks` — outbound webhook delivery
- `rag_tasks` — RAG document indexing
- `cron_tasks` — periodic cleanup

## Architecture Decision Records

Key architecture decisions (full ADRs in [08-decisions/](./08-decisions/README.md)):

| Decision | Summary | Status |
|---|---|---|
| SCIP as default solver | PySCIPOpt, evolving to multi-solver | Accepted |
| RabbitMQ + Celery | AMQP durability, Redis result backend | Accepted |
| Multi-tenancy | Shared DB with organization_id scoping | Accepted |
| Modular monolith | Feature-led domain extraction, solver-first | Accepted |
