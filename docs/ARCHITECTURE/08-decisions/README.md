# Architectural Decision Records — Index

> Quick links to documented architecture decisions. Most live as "phase decisions" (D-xx) inside each CONTEXT.md; top-level ADRs are captured here when they span multiple phases.

## Global ADRs

| ID | Title | Date | Location |
|----|--------|-------|-----------|
| **ADR-001** | Modular monolith · feature-led extraction · Solver first | 2026-04-08 | Foundational |
| **ADR-002** | Solver adapter pattern with `typing.Protocol` (not ABC) | 2026-04-13 | Phase 04 decisions |
| **ADR-003** | Local RAG with sentence-transformers + Qdrant (CPU, 384 dims) | 2026-02-xx | Pillar-1 RAG research |
| **ADR-004** | Dynamic queue routing in the producer (no static `task_routes`) | 2026-04-17 | Phase 06 decisions D-01..D-03 |
| **ADR-005** | Maintenance mode migration via DB flag (no header, no env var) | 2026-04-17 | Phase 06 decisions D-19..D-22 |

## Decisions by phase

Each phase captures its decisions as `D-01`, `D-02`, ... in its `*-CONTEXT.md`. Completed phases:

| Phase | Topic | Relevant decisions | CONTEXT |
|------|------|----------------------|-----------|
| 01 | Prerequisites | D-05 GHCR, D-07 pre-built worker image, D-08 `docker compose pull` | `01-CONTEXT.md` |
| 02 | Directory structure + shared kernel | `app/shared/` structure, boundary rules | Phase 02 CONTEXT |
| 03 | Solver domain extraction | first bounded context extracted | Phase 03 CONTEXT |
| 04 | SolverAdapter Protocol | interface + exception hierarchy | `04-CONTEXT.md` |
| 05 | HiGHS adapter | D-05..D-07 propagation chain, defaults, 422 unavailable | `05-CONTEXT.md` |
| **06** | **Celery + Docker multi-solver** | **29 decisions D-01..D-29** (routing, resources, rollout, observability) | `06-CONTEXT.md` |

## Highlighted Phase 6 decisions

| D | Decision |
|---|----------|
| D-01 | Keep `solve_async` / `solve_model_async` as the only tasks; the producer picks the queue in `apply_async` |
| D-02 | `SOLVER_QUEUE_MAP` in `queue_routing.py` as the single extension point |
| D-05 | Defense in depth: strict `-Q` + runtime guard `_assert_queue_match` |
| D-12 | SCIP worker 3 G / 2.0 CPU / 256 pids |
| D-13 | HiGHS worker 1 G / 1.0 CPU / 128 pids |
| D-14 | Default worker 256 M / 0.25 CPU (OOM risk on financial batch jobs, alert documented) |
| D-18 | Rollout: drain + rotate (not blue/green) |
| D-21 | Drain window 600 s (aligned with the Business cap) |
| D-22 | Rollback via `git revert` + `compose up` (no feature flags) |
| D-26 | `celery-exporter` (danihodovic) pinned by sha256 |
| D-28 | 3 new alerts in `jaot-celery`: SolverQueueBacklogWarn/Critical, DefaultQueueOOMRisk |

## How to add an ADR

1. If the decision affects **a single phase** → capture it in that phase's `*-CONTEXT.md` as `D-nn`.
2. If the decision **spans multiple phases** → create `docs/ARCHITECTURE/08-decisions/ADR-XXX-title.md` and add it to the table above.
3. Minimum format: Context · Decision · Consequences · Alternatives considered.
