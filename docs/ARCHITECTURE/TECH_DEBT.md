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
| D-05 | `WR-03`: `SolverNotFoundError` exposes the full solver list | Medium (license info leak in Phase 7) | 1 h | ✅ **Resolved** |
| D-06 | `WR-06`: `celery_beat` uses the `app.core.celery_app` shim while workers use the canonical module | Low (cosmetic) | 15 min | ✅ **Resolved** (by D-01) |
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

## D-05 · WR-03 · Solver refusals as a licence oracle — ✅ RESOLVED

**What:** `GET /solvers/available` lists only adapters whose `is_available()` is true, so a
commercial solver that is installed but unlicensed is deliberately absent. The refusal
messages handed that back: `SolverNotFoundError` said a name was *not registered* while
`SolverUnavailableError` said it *was registered but not available at runtime*, and both
reached the client verbatim through `detail=str(exc)`. Probing names enumerated which
commercial solvers the deployment carries — information about the operator's licences.

**Status:** ✅ **Resolved** — `app/api/v2/solver_errors.py` maps both exceptions to one 422
body (`Solver '<name>' is not available.`) at all four call sites (`solve.py`,
`routes/models/execution.py` ×2, `routes/models/analysis.py`). The real reason is logged
server-side, where it is a diagnostic rather than an oracle; the stored execution error
keeps it too, since that row is the operator's own record. Pinned by
`tests/unit/test_solver_error_uniformity.py`.

---

## D-06 · `celery_beat` on the shim — ✅ RESOLVED (by D-01)

**What:** beat was documented as booting through `app.core.celery_app` while the workers
used the canonical module.

**Status:** ✅ **Resolved** — `app/core/` no longer exists (D-01 removed every shim), and
both compose files start beat with `-A app.shared.core.celery_app`, the same module the
workers use. Nothing left to change; verified 2026-07-26.

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
4. ~~**Cosmetic** — D-05, D-06 when time allows.~~ ✅ Done (2026-07-26).

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
| D-13 | 7 handlers did genuinely heavy work on the loop — MPS/LP parsing, 16 MB dataset parsing, PDF text extraction, boto3 uploads, SCIP export — not the short commits the audit assumed | Medium | 1 day | ✅ **Resolved** (`2b81868`) |
| D-14 | 23 foreign keys with no index | Low-medium (scales badly) | 0.5 day | ✅ **Resolved** — 18 indexed (`20260726_index_fks`); the other 5 deliberately skipped: they point at `model_catalog` / `organization_models` (legacy DROP list) or at ADR-008 orphans with no ORM model |
| D-15 | No `import-linter` contract on the vertical direction (api → services → domains), which is why D-16 went unnoticed | Medium (architectural) | 0.5 day | ✅ **Resolved** — contract 7, D-16's call sites frozen as listed exceptions |
| D-16 | Upward imports: `domains → services` (11), `domains → api` (7), `shared → services` (9 — a gap in an existing contract) | Medium (blocks extraction) | 1 day | Medium |
| D-17 | 55 endpoints return `dict[str, Any]` with no `response_model` → OpenAPI cannot describe them and the frontend hand-writes those types | Medium (contract drift) | 2–3 days | 🔸 **Started** — 53 left; favourites and recents now answer with declared schemas |
| D-18 | 113 `Depends(get_db)` instead of the `DBSession` alias the project rule mandates | Low (consistency) | Folded into D-12 | Low |
| D-19 | `execution.py` had grown to 839 LOC mixing the marketplace execution flow with the post-solve analysis endpoints, and the org filter was hand-typed at 4 call sites | Low-medium (architectural) | 1–2 days | ✅ **Partly resolved** (`f4dd487`) — analysis split into its own module + one shared `execution_or_404`; the remaining ~180 route-level queries stay as opportunistic cleanup |
| D-23 | The two API rate limits are enforced from a COPY on `organizations` (written at signup, read by 9 call sites) instead of from the instance profile. Editing them in the panel is made to work by propagating the change to the organizations still on the old value — honest, but a mirror that can drift. The deep fix is a nullable column meaning "inherit", which needs a schema change the rollback window cannot take today | Low (works; the mechanism is the debt) | 0.5 day | Deferred — do it with the contract-release schema pass |
| D-22 | Orphaned `platform_settings` rows — 98 on the reference install, of which 51 come from the 1.9 panel review (23 retired settings + the 28 `plan_*` tier keys the instance profile replaced) and the rest predate it, mostly ADR-008 billing keys. Additive-only means the code stopped reading them but nothing deleted them | Low (cosmetic; invisible to the panel, which renders the registry) | Minutes | ✅ **Resolved** (`20260728_prune_orphan_settings`) — 186 rows → 88, exactly the registry |

**Suggested first batch:** D-10 + D-11 + D-12 — the three that change something real, ~2 days,
no architectural commitment.

**D-15 · ✅ Resolved (2026-07-26) — and it now carries D-16's inventory.**
Contract 7 in `pyproject.toml` (`domains-no-upward-imports`) forbids
`app.domains → app.services` and `app.domains → app.api`. The 17 call sites that exist
today are listed as `ignore_imports` rather than fixed, because untangling them *is*
D-16 and several want an injected port or an event rather than a moved import. What the
contract buys immediately:

- **The debt cannot grow.** A new upward import fails `lint-imports` with file and line.
  Verified by adding one deliberately and watching the build go red.
- **The inventory lives where the build reads it**, not in prose here. Deleting an entry
  as D-16 lands makes the contract stricter for free, and an entry that no longer matches
  a real import makes import-linter complain — so the list cannot rot.

One entry is not a domain dependency at all: `app.shared.core.celery_app →
app.services.email_service` is a transitive chain the domain inherits by importing the
Celery app, already deferred inside `worker_process_init` where it belongs. It belongs to
the `shared → services` strand of D-16.

**D-16 grew by one (2026-07-26).** Rolling a solve onto its marketplace listing needs the
listing statistics writer in `app/services/marketplace_fusion.py`, so
`app/domains/solver/tasks/solve_tasks.py` imports it. The right shape is the solver
*telling* the marketplace a solve finished, not fetching its writer — an event or an
injected port, not another module to shuffle.

**Not proposed:** microservices (discarded by the owner, 2026-07-25), a dynamic `auto_router`
(discarded with rationale — its reason slugs are public API contract), and an async-SQLAlchemy
migration (ADR-009 gets the same benefit for a fraction of the cost).

**Still deferred:** the contract-release work (legacy `DROP`s, `/seller/*` → `/author/*`,
`favorite.py` `Column()`). Additive-only discipline makes the `DROP`s release-shaped, not
refactor-shaped — they need their own window, and until they land
`alembic --autogenerate` stays unreliable.

**D-22 · ✅ Resolved (2026-07-28) — and it did not need that window.**
`20260728_prune_orphan_settings` deletes the 98 rows by an explicit list, grouped by where
each came from: 43 `plan_*` tier keys, 31 billing/marketplace keys from ADR-008, and 24 the
1.9 review retired. The reference install went from 186 rows to 88 — exactly the registry —
and a restart logged *"All platform settings present in database"*, confirming the self-heal
does not put them back.

It was deferred here on the assumption that it belonged with the schema `DROP`s. It does
not, and the distinction is worth keeping: that window exists because rollback restores
images, not schema, so an image that still selects a dropped column crashes. Deleting *rows*
has no such failure mode — an older image re-seeds any key its own registry declares on the
next boot, and the numbers that mattered (an operator's own plan limits) were already carried
into `instance_*` by `20260727_instance_limits`. What a rollback would lose is a customised
value on a row nothing reads.

The explicit list is what makes the migration deterministic and auditable, and also what
could go wrong — a key in it that the registry still declares would wipe a live setting. A
`CONTRACT-TEST` in `tests/api/test_admin_settings.py` intersects the two and fails if they
ever overlap.

**D-17 · 🔸 Started (2026-07-28): 55 → 53.**
The favourites shelf and the recently-opened list are the two endpoints behind one screen,
and both returned `dict[str, Any]`. They answer with declared schemas now
(`FavoriteListResponse`, `RecentListResponse`), and their queries moved out of the route into
`app/services/favorites_service.py` — one of the opportunistic route-level cleanups D-19 left
open. The summaries are deliberately narrower than `ModelCatalogResponse`: that shelf renders
a card, not a listing page.

Typing them found a defect rather than merely describing one. `access_count` is a `String`
column, so the count reached the browser quoted, while the page that renders it declares a
number and hands it to a plural rule. The schema converts it, and a test pins the type.

One note for whoever finishes D-17, found while writing those tests: **nothing in the backend
ever inserts a `recent_models` row.** Reading it, erasing it for GDPR and the P1.5 backfill of
its key are the only code that touches the table, so the "Recent" tab shows whatever legacy
rows an install still carries and nothing more. Typing the endpoint does not change that —
what counts as "opening" a model is a product decision, not a cleanup.

**Addendum (same day, after owner review):** two precisions on the audit above.

- **D-12 has a clear head of the queue.** ADR-007 already removed every in-request solve, so
  F-01 is not about solving — but `get_async_solve_status` (`solve.py:1257`), the endpoint the
  studio **polls for the whole duration of every solve**, is an `async def` that queries the DB
  on the event loop. Highest-traffic item in F-01; it is in the mechanical group.
  `cancel_async_task` (`solve.py:1362`) has the same shape and negligible traffic.
- **D-20 — ✅ RESOLVED (`f4dd487`):** `deploy/docker-compose.prod.yml:199-201` still justifies the API
  container's 5 GB / 6 CPU limits with "SCIP sync solves on large models" — a rationale ADR-007
  retired in July 2026. Harmless (it is a ceiling, not a reserve) but misleading for the next
  capacity decision. Rewritten to the real reason the headroom exists: the API does load SCIP
  — to import an MPS/LP, to export a model, and to validate a submitted problem — plus a note
  that exports are written to the 256 MB tmpfs, which counts against the same memory limit.

---

## D-21 · Capacity limits inherited from the paid tiers — ✅ RESOLVED

**Found:** while measuring how large a transport model JAOT can actually take (the MDPDPTW
scale work), a 1000×1000 assignment model failed — not in the solver, not in the compiler,
but in Pydantic: `Objective.expression` was capped at 5,000,000 characters. The cap had
already been raised once (500K → 5M, 2026-06-29) for exactly the same reason, which is the
tell that the number was never principled.

**Why it mattered:** a 400×400 assignment model — a *small* haulage fleet, per the owner's
domain input — grounds to a **3,679,901-character** objective. The platform was operating
at 74 % of a hard wall on a problem size its target market considers trivial, and 500×500
failed outright.

**The wider finding:** that constant was not alone. JAOT was sold in tiers before ADR-008
removed billing, and the shape survived everywhere — `threads ≤ 8` (on a machine the
operator owns), `time_limit ≤ 24 h`, a hardcoded 50 MB body limit, `max_variables ≤ 10 M`
enforced as a *registry ceiling* so the admin panel refused a larger number even from the
instance owner, and limit errors that returned `upgrade_to: "Pro"` / `upgrade_url:
"/billing"` — an upsell to tiers that no longer exist, pointing at a page ADR-008 deleted.

**Resolution.** Every capacity limit is now removed or operator-configured, with **0 =
unlimited** throughout: expression caps deleted, `MAX_REQUEST_BODY_MB` (default 0) replaces
the hardcoded 50 MB, `threads` and `time_limit_seconds` unbounded, the grounding budget
moved to `dsl_max_grounded_elements`, and no plan field has a registry ceiling. The upsell
fields are gone; errors now carry `setting_key`.

Two real bugs surfaced while doing it, both of which would have made the new "0 = unlimited"
contract a trap:

1. **The grounding budget was applied inconsistently** — the range (`1..n`) and computed
   `cross` checks read `MAX_GROUNDED_ELEMENTS` directly instead of the value threaded
   through `compile_jmodel`, so raising or disabling the budget left them enforcing the old
   number.
2. **A rate limit of 0 blocked every request.** The check is `count >= limit`, immediately
   true at zero — an operator setting 0 to mean "unlimited" would have locked their own
   instance out entirely.

**Measured after the change** (HiGHS, proven optimal): 1000×1000 → 905,400 variables, a
**23.5 M-character** objective, 147 s; 1500×1500 → 2,044,800 variables, **54.5 M
characters**, 532 s at 8.5 GB RSS. The expression parser was never the bottleneck — it is
linear, and chewed through 2 M terms (42.7 MB) in 13 s. Memory is the only ceiling left,
which is precisely the operator's call to make.

**Kept on purpose:** limits that protect a *real external cost* rather than a made-up notion
of "too big" — the `/dsl/generate` request caps and the LLM attachment cap, since every byte
there is forwarded to Anthropic and billed against the monthly EUR budget.
