# Identified Technical Debt

> Findings from the comparative audit of pre-refactor vs HEAD (2026-04-18). Ordered by **benefit / effort** ratio.

**Overall verdict:** 58% essential complexity (justified by multi-solver) / 42% accidental (avoidable). See the reasoning at the end.

---

## Executive summary

| # | Debt | Impact | Effort | Priority |
|---|-------|---------|----------|-----------|
| D-01 | 79 compat shims in `app/core/` | Medium (cognitive friction) | 1–2 sprints | ✅ **Resolved** |
| D-02 | `import-linter` contracts consolidated (6→5) | Low (PR friction) | 0.5 day | ✅ **Resolved** |
| D-03 | **CR-01**: double refund possible in `cancel_async_task` | **High (monetary loss)** | 2–3 days | ✅ **Resolved** |
| D-04 | **CR-02**: IDOR in `GET /api/v2/models/async/{task_id}` | **High (cross-tenant leak)** | 1 day | ✅ **Resolved** |
| D-05 | `WR-03`: `SolverNotFoundError` exposes the full solver list | Medium (license info leak in Phase 7) | 1 h | Medium |
| D-06 | `WR-06`: `celery_beat` uses the `app.core.celery_app` shim while workers use the canonical module | Low (cosmetic) | 15 min | Low |
| D-07 | `CeleryWorkerDown` alert still references the legacy container | Medium (alert silenced post-rotate) | 15 min | **High (pre-rotate)** |
| D-08 | 5 consecutive `fix(ci):` commits (fixtures + postgres readiness) | Medium (flaky pipeline) | Resolved in `9357e9dd` | Monitor |
| D-09 | The server 180 commits behind + CI red for 7 days | High (blocks Phase 6 UAT) | 1 day (fix CI → deploy) | **High** |

---

## D-01 · Compatibility shims (~79 files / ~600 LOC) — ✅ RESOLVED

**What:** files like `app/core/rate_limiter.py` that re-exported from `app/shared/core/rate_limiter.py`. `app/core/` has been fully removed; all callers import from `app/shared/` directly.

**Why it was needed:** The ~46 legacy callers were kept working untouched during the Solver domain extraction. The shim caused the rate-limiter patch loop (5 `fix(ci):` commits) because a race condition between `pytest` collection and the autouse fixture wrote flags into the wrong module.

**Resolution:** `app/core/` directory deleted. Legacy callers updated to `app/shared/core/`. The `_bypass_rate_limiter` fixture now loads the real module before collection (`9357e9dd`).

---

## D-02 · `import-linter` contracts — ✅ RESOLVED (6→5)

**What:** 6 contracts in `pyproject.toml`. The `solver-domain-no-shim-imports` contract forced moving `queue_routing.py` from `app/shared/core/` to `app/domains/solver/` (commit `8fe5dbdf`) — a good sign, but it was consolidated with the general `shared-no-import-domains` contract (D-16).

**Resolution:** collapsed contracts 3+5 into `shared-and-solver-domain-no-shim-imports`. Now 5 contracts with the same enforcement surface. See `05-import-linter.md`.

---

## D-03 · CR-01 · Double refund on cancel (CRITICAL)

**What:** `cancel_async_task` in `app/api/v2/solve.py:628-665` uses `revoke(terminate=True, SIGTERM)`. The worker falls into `except Exception` and refunds the prepayment, **while the cancelling call may also issue a refund**. Credits get credited twice.

**Severity:** Critical — direct monetary loss.
**Status:** ✅ **Resolved** — a partial unique index `uq_credit_txn_reference` on `credit_transactions (organization_id, transaction_type, reference_type, reference_id)` makes refunds idempotent (migration `20260317_add_credit_idempotency_constraint`); a duplicate refund for the same execution violates the constraint instead of double-crediting. *(Later made moot: the entire credit system was removed by ADR-008.)*

---

## D-04 · CR-02 · IDOR in `/models/async/{task_id}` (CRITICAL)

**What:** `get_async_execution_status` in `app/api/v2/routes/models/execution.py:275-352` **does not validate ownership** — any authenticated user holding the `task_id` can see any execution. Cross-tenant leak.

**Severity:** Critical — multi-tenancy violation.
**Status:** ✅ **Resolved** — the lookup now filters by tenant:
```python
exec = db.query(ModelExecution).filter(
    ModelExecution.celery_task_id == task_id,
    ModelExecution.organization_id == current_user.organization_id,
).first()
```

---

## D-07 · CeleryWorkerDown alert (PRE-ROTATE)

**What:** `monitoring/prometheus/alert_rules.yml:327-334` references the legacy container `jaot_prod_celery`. Post-rotate that container disappears → the alert goes silent without notifying anyone.

**Fix:** already corrected in HEAD — the rule now uses `name=~"jaot_prod_celery_(default|scip|highs)"`. Verified in `06-VERIFICATION.md` test 4 (pass).

---

## D-08 · Flaky rate-limiter shim (RESOLVED)

**What:** the autouse `_bypass_rate_limiter` fixture wrote flags into the placeholder module if a test imported the real one AFTER the shim had been initialized.

**Patch progression:**
| Commit | Action | Type |
|--------|--------|------|
| `e3906d1e` | belt-and-suspenders `_force_real` | patch |
| `9357e9dd` | load real module BEFORE collection | root fix ✓ |

**Status:** stable since `9357e9dd`. Removing the shims (D-01) will prevent recurrences.

---

## D-09 · The server behind + CI red (URGENT)

**What:** last successful deploy `485f6cc6` on 2026-04-10. The server 180 commits behind. CI red since 2026-04-11 (pipelines 146-160 exit 1).

**Current status:** ✅ Resolved — CI went green after `9357e9dd` and the server has been deploying continuously since. This entry is a snapshot from the Phase 6 rollout, kept for the audit trail.

**Blocks:**
- Phase 6 UAT Tests 1/2/3 (rotation on the server, live Grafana, alerts under load)
- Any release until CI is green

**Plan:**
1. `git push origin main` and watch the pipeline.
2. If green → `deploy.sh deploy` on the server (not `multi-solver-rotate` yet).
3. If green + server up to date → run `multi-solver-rotate` (dry-run first).

---

## Why 58% essential / 42% accidental

| Metric | Pre-refactor | HEAD | Δ |
|---------|---------------:|-----:|--:|
| `.py` files in `app/` | 328 | 351 | +7% |
| LOC in `app/` | 57 674 | 50 555 | **-12%** |
| Infra LOC (docker + deploy + CI) | 2 209 | 2 903 | +31% |
| Services in `docker-compose.prod.yml` | 29 | 31 | +2 workers |
| Bounded contexts extracted | 0 | 1 | +1 |
| `import-linter` contracts | 3 | 5 | +2 (net, after 6→5 consolidation) |
| Dependencies in `app/api/deps.py` | 263 LOC | 291 LOC | +10% |
| Shims in `sys.modules` | ~0 | 0 (removed) | ✅ D-01 resolved |

**Essential:** multi-solver required 2 new workers + queue routing + resource isolation. The -12% LOC in `app/` proves the modularization **compacted** the codebase rather than inflating it.

**Accidental:** the 79 shims and the 5 back-to-back `fix(ci):` commits were self-inflicted friction from not breaking legacy imports. Both are now resolved (D-01, D-02).

---

## Recommended attack order

1. ~~**Urgent** — D-09 (unblock CI and the server), D-07 (pre-rotate alert).~~ ✅ Done.
2. ~~**Security** — D-03 (CR-01 double refund), D-04 (CR-02 IDOR).~~ ✅ Resolved.
3. ~~**Architecture** — D-01 (shims), D-02 (import-linter contracts).~~ ✅ Resolved.
4. **Cosmetic** — D-05, D-06 when time allows.

---

# Backend audit 2026-07-26 — D-10 … D-19

> Second full audit of `app/` (299 files, 61,149 LOC), this time against ADR-001 and the
> project's own rules rather than against a pre-refactor baseline. Findings, evidence and
> the things that turned out to be **fine** are in
> [`02-backend/07-audit-2026-07-26.md`](02-backend/07-audit-2026-07-26.md); the concurrency
> rule it proposes is [ADR-009](08-decisions/ADR-009-sync-endpoints-with-a-sync-session.md).
>
> **Owner decision (2026-07-26): report only.** Nothing below has been implemented; these
> are candidates, ordered by benefit ÷ effort.

| # | Debt | Impact | Effort | Priority |
|---|------|--------|--------|----------|
| D-10 | `/api/v2/health` blocked the event loop 100 ms per call via `psutil.cpu_percent(interval=0.1)` | Medium (availability) | Minutes | ✅ **Resolved** (`7a7623c`) |
| D-11 | CI had **no** security gate at all — they were lost in the Woodpecker→GHA migration, while `app/CLAUDE.md` claimed they ran | Medium (supply chain) | 0.5 day | ✅ **Resolved** — `pip-audit` (strict) + `bandit -lll` + `npm audit` (critical blocks, high informational) |
| D-12 | 113 endpoints were `async def` with no `await` yet issued synchronous DB calls → every query stalled the event loop (4 workers in prod) | Medium-high (concurrency ceiling) | 1 day | ✅ **Resolved** (`27c1ae8`, ADR-009 Accepted) |
| D-13 | 10 endpoints mix a real `await` with synchronous `db.commit()` — need the DB work moved off the loop, case by case | Medium | 1 day | Medium |
| D-14 | 23 foreign keys with no index (incl. `users.organization_id`, `api_keys.user_id`, `refresh_tokens.user_id`) | Low-medium (scales badly) | 0.5 day | Medium |
| D-15 | No `import-linter` contract on the vertical direction (api → services → domains), which is why D-16 went unnoticed | Medium (architectural) | 0.5 day | Medium |
| D-16 | Upward imports: `domains → services` (10), `domains → api` (7), `shared → services` (9 — a gap in an existing contract) | Medium (blocks extraction) | 1 day | Medium |
| D-17 | 55 endpoints return `dict[str, Any]` with no `response_model` → OpenAPI cannot describe them and the frontend hand-writes those types | Medium (contract drift) | 2–3 days | Medium |
| D-18 | 113 `Depends(get_db)` instead of the `DBSession` alias the project rule mandates | Low (consistency) | Folded into D-12 | Low |
| D-19 | 187 direct queries in `app/api/` — routes are also the data layer; `execution.py` now 839 LOC | Low-medium (architectural) | 1–2 days | Low |

**Suggested first batch:** D-10 + D-11 + D-12 — the three that change something real, ~2 days,
no architectural commitment.

**Not proposed:** microservices (discarded by the owner, 2026-07-25), a dynamic `auto_router`
(discarded with rationale — its reason slugs are public API contract), and an async-SQLAlchemy
migration (ADR-009 gets the same benefit for a fraction of the cost).

**Still deferred:** the §5 contract-release work (legacy `DROP`s, `/seller/*` → `/author/*`,
`favorite.py` `Column()`). Additive-only discipline makes the `DROP`s release-shaped, not
refactor-shaped — they need their own window, and until they land
`alembic --autogenerate` stays unreliable.

**Addendum (same day, after owner review):** two precisions on the audit above.

- **D-12 has a clear head of the queue.** ADR-007 already removed every in-request solve, so
  F-01 is not about solving — but `get_async_solve_status` (`solve.py:1257`), the endpoint the
  studio **polls for the whole duration of every solve**, is an `async def` that queries the DB
  on the event loop. Highest-traffic item in F-01; it is in the mechanical group.
  `cancel_async_task` (`solve.py:1362`) has the same shape and negligible traffic.
- **D-20 (new, minutes):** `deploy/docker-compose.prod.yml:199-201` still justifies the API
  container's 5 GB / 6 CPU limits with "SCIP sync solves on large models" — a rationale ADR-007
  retired in July 2026. Harmless (it is a ceiling, not a reserve) but misleading for the next
  capacity decision.
