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
| D-16 | Upward imports: `domains → services` (11), `domains → api` (7), `shared → services` (9 — a gap in an existing contract) | Medium (blocks extraction) | 1 day | ✅ **Resolved (2026-07-29)** — 6 were never debt (a domain's routes ARE its API layer), 2 reached into another endpoint's privates (now a named module), 5 moved down or died, and the last 3 became host ports the domain declares (`app/domains/solver/ports.py`) and JAOT registers at both boots |
| D-17 | 55 endpoints return `dict[str, Any]` with no `response_model` → OpenAPI cannot describe them and the frontend hand-writes those types | Medium (contract drift) | 2–3 days | ✅ **Resolved (2026-07-30)** — 44, not 55: measured with an AST walk, both earlier counts included handlers annotated `-> dict[str, Any]` that already declare a `response_model`. All 44 now declare one, and typing them surfaced two bugs (see below) |
| D-18 | 113 `Depends(get_db)` instead of the `DBSession` alias the project rule mandates | Low (consistency) | Folded into D-12 | Low |
| D-19 | `execution.py` had grown to 839 LOC mixing the marketplace execution flow with the post-solve analysis endpoints, and the org filter was hand-typed at 4 call sites | Low-medium (architectural) | 1–2 days | ✅ **Resolved where it bit** (`f4dd487` + 2026-07-29) — analysis split out; both org-scoped lookups that were being re-typed now have one shared helper each. The remaining 164 route-level queries are single reads with no repeated shape — audited for missing org filters, none found |
| D-23 | The two API rate limits are enforced from a COPY on `organizations` (written at signup, read by 9 call sites) instead of from the instance profile. Editing them in the panel is made to work by propagating the change to the organizations still on the old value — honest, but a mirror that can drift. The deep fix is a nullable column meaning "inherit", which needs a schema change the rollback window cannot take today | Low (works; the mechanism is the debt) | 0.5 day | ✅ **Resolved (2026-07-31)** — and it never needed the schema change: a nullable "inherit" column is only required if a *per-organization* limit exists, and this instance has one profile for everyone. The limiter reads the instance setting; the columns stay and are still written, so rollback is exact |
| D-24 | Nothing a public path learned about its caller was usable, and nothing it wrote survived. `recent_models` had no writer at all; `model_view_events` was flushed and never committed; and the opportunistic principal the auth middleware attaches came back expired, so reading `user.id` raised — a swallowed exception in the telemetry, a 500 in the contact form | Medium-high (silent data loss on three live surfaces, one of them user-facing) | 0.5 day | ✅ **Resolved (2026-07-28)** — principal detached before its session closes, writes committed |
| D-22 | Orphaned `platform_settings` rows — 98 on the reference install, of which 51 come from the 1.9 panel review (23 retired settings + the 28 `plan_*` tier keys the instance profile replaced) and the rest predate it, mostly ADR-008 billing keys. Additive-only means the code stopped reading them but nothing deleted them | Low (cosmetic; invisible to the panel, which renders the registry) | Minutes | ✅ **Resolved** (`20260728_prune_orphan_settings`) — 186 rows → 88, the registry as it stood that day (87 since the solver pool-size setting was removed) |

**Suggested first batch:** D-10 + D-11 + D-12 — the three that change something real, ~2 days,
no architectural commitment.

**D-15 · ✅ Resolved (2026-07-26) — and it now carries D-16's inventory.**
Contract 7 in `pyproject.toml` (`domains-no-upward-imports`) forbids
`app.domains → app.services` and `app.domains → app.api`. The 17 call sites that existed
were listed as `ignore_imports` rather than fixed, because untangling them *was* D-16 —
that list has since been emptied as D-16 landed (2026-07-29); what remains is the stated
routes-are-API rule and one transitive edge that was never the domain's. What the
contract bought immediately:

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
1.9 review retired. The reference install went from 186 rows to 88 — the registry as it stood
that day — and a restart logged *"All platform settings present in database"*, confirming the
self-heal does not put them back. The registry has been 87 since the solver pool-size setting
was removed the next day, so 87 is the figure to compare a live count against now.

Production kept three rows past this prune, because the list was built from a development
inventory that had never had Featurebase configured — see the Featurebase follow-up below.

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
ever overlap; it is parametrised over every prune migration, so a later one cannot skip it.

**Featurebase follow-up · ✅ Resolved (2026-07-31).** Production carried 90 rows against 87
declared, and the difference was exactly `FEATUREBASE_DEFAULT_BOARD`, `FEATUREBASE_JWT_SECRET`
and `FEATUREBASE_ORG` — configuration for the hosted feedback board GitHub Issues replaced.
`20260731_prune_featurebase` deletes them the same way, and logs how many rows it actually
matched: `key` compares exactly, so an install that spelled them differently would delete
nothing and still report success, and one of the three is a secret whose whole point is to stop
being stored. **The lesson generalises past this migration:** a delete list built from a
development inventory only covers what development happened to have configured. For anything
row-scoped, take the inventory from the install that has the rows.

**D-17 · ✅ Resolved (2026-07-30). It started here (2026-07-28) at 55 → 53.**
The favourites shelf and the recently-opened list are the two endpoints behind one screen,
and both returned `dict[str, Any]`. They answer with declared schemas now
(`FavoriteListResponse`, `RecentListResponse`), and their queries moved out of the route into
`app/services/favorites_service.py` — one of the opportunistic route-level cleanups D-19 left
open. The summaries are deliberately narrower than `ModelCatalogResponse`: that shelf renders
a card, not a listing page.

Typing them found a defect rather than merely describing one. `access_count` is a `String`
column, so the count reached the browser quoted, while the page that renders it declares a
number and hands it to a plural rule. The schema converts it, and a test pins the type.

Writing those tests turned up something the typing could not fix on its own: **nothing in the
backend ever inserted a `recent_models` row.** That became D-24 below, and is now closed.

**The count was wrong, in our favour (2026-07-29): 44, not 55.** Both the original figure and
the "53 left" that replaced it counted handlers annotated `-> dict[str, Any]`. Eleven of those
already declare a `response_model`, which is the part that matters — OpenAPI describes them
and a generated client can see them; the annotation on the Python function is cosmetic beside
that. `triggers.py` is the clearest case: eight handlers annotated `dict`, every one of them
typed in its decorator. Measured with the AST instead of by grep, the endpoints OpenAPI
genuinely cannot describe are **44**, and they are spread thin — the worst file has five.

**All 44 declare one now (2026-07-30), and five deliberately do not.** The five are SSE
endpoints (`/messages` and the four explainers): a `response_model` there would describe a
body that does not exist, so they declare `response_class=EventSourceResponse`, which is the
only true thing OpenAPI can say about a stream. Two endpoints answer with a genuine union —
`POST /solve/async` and `POST /models/{id}/execute` return either the queue acknowledgement or
the result — and the two members are disjoint by construction (`SolverStatus` has no
`"pending"`, and `solve_time_seconds` is required), so the union cannot serialise the wrong
one. Paths that degrade to 202 return a `JSONResponse`, which bypasses the `response_model`
entirely; endpoints that only degrade that way therefore declare the exact model.

**Typing them found two bugs rather than merely describing them.** The reported-reviews queue
crashed on the first flagged review: the page read `report_count` and `report_reasons`, and
neither exists on `ModelReview` — it carries an `is_reported` boolean and a single
`report_reason`. Reading `.length` off `undefined` threw during render. The same endpoint
omitted `is_visible`, which is what the hide/show toggle reads, so every row rendered as
hidden. And the execution poll reported a false "completed": the last progress tick carries
`status: "completed"` while Celery is still in PROGRESS, and spreading the task meta *after*
the handler's own keys let it overwrite `"running"` — the exact defect `/solve/async` fixed
after a live incident on 2026-07-17, still present in its twin in `routes/models/execution.py`.
The fix and its comment existed; the second entry point never got them. A test pins it, and
fails with the bug restored.

**D-23 · ✅ Resolved (2026-07-31) — the schema change it was waiting for was never needed.**
The deferral above rested on a premise that had stopped holding: a nullable column meaning
"inherit" is only necessary if a *per-organization* limit exists to inherit from. It does not.
This platform runs one instance with one set of request limits for everyone, so the limiter
reads the instance setting directly and the mirror on `organizations` stops being an input.
The columns are left in place and still written at signup — additive-only, and a rollback to
the previous images finds exactly the data they expect.

The same pass retired the `plan` field from code and UI. It had 16 usages and not one of them
decided anything: ADR-008 removed billing, and D-21 removed the capacity ceilings that were
the last thing a tier could still mean. The column stays, for the same rollback reason.

**D-24 · ✅ Resolved (2026-07-28) — three dead surfaces, two causes, and a harness that hid
both.** Start at the visible end: the "Recent" tab read a table nothing wrote. Fixing that
meant deciding what counts as opening a model. The write goes on the marketplace detail
page, because that is where the Recent cards themselves link and where the visit was already
being recorded. *Using* a model is a different thing and is already kept — that is what
executions are.

**Cause one: nothing committed.** `get_db` closes the session and never commits, and the
view/impression writers only flushed, so every analytics event since the feature shipped was
discarded on the way out. Not a slow leak — nothing was ever stored, on any install.
Measured before the fix against the running server: 108 published listings, one catalog
request and one detail request, `model_view_events` still empty.

**Cause two: the principal arrived dead.** On a public path the auth middleware
authenticates in its own session and closes it *before* the handler runs, and resolving a
principal commits (the API key's `last_used_at`), which under the default `expire_on_commit`
expires every instance it just loaded. So `user.id` in a public handler was not a read but a
`DetachedInstanceError` — swallowed by the telemetry's broad except, and **a 500 in the
contact form**, for exactly the signed-in visitors that auto-tagging exists to serve. The
middleware now refreshes anything a commit expired and detaches the principal before its
session closes, so what it hands over stays readable.

**Why no test caught either.** The suite gives that middleware an
`expire_on_commit=False` sessionmaker, so instances survive there whatever the handler does
— the harness was more forgiving than production in precisely the place that mattered. And
every assertion involved was a status code, which stayed 200 throughout. The new
`CONTRACT-TEST`s count rows instead, and two of them recreate production's session settings
to prove the point: with the fix reverted they fail, one on `DetachedInstanceError` and one
on an empty table.

The visit write is an upsert on `(user_id, model_project_id)`, so two tabs open at once
update one row instead of racing into an integrity error, and it runs inside a `SAVEPOINT`:
telemetry is not worth a reader's page. `access_count` stays a `String` column — it joins
`favorite.py`'s `Column()` on the contract-release list; the increment casts through integer
in the meantime.

**D-19 · ✅ Resolved where it bit (2026-07-29) — after checking where that actually was.**
What was left of D-19 read as "~180 route-level queries", which invites a mechanical sweep
into services. Two questions decided the shape of the work instead.

**Do those queries hide a cross-tenant leak?** The project's own rule says a missing
`organization_id` filter is a security bug, so that is worth knowing before anything else.
Every query on an org-scoped model was matched against its filter chain: 58 came back with
no organization filter in sight, and each was read. **All 58 are correct** — they filter by
`user_id` (strictly narrower), fetch-then-authorize (the execution WebSocket closes with
4003 right after loading), look up by a secret token hash, serve the public marketplace, or
sit behind the admin router's `dependencies=[Depends(get_admin_user)]`, which covers the six
admin modules that never name `AdminUser` themselves. **Nothing to fix.**

**Is any query shape written more than once?** That is the part that actually bit — the
audit's own F-09 was one lookup re-typed at four call sites. Two shapes were:

- `execution_or_404` already existed, and `llm.py` (×3) and `solve.py` re-typed it anyway,
  identical down to the 404 detail string. Now they call it. Two of those also carried a
  function-local `import ModelExecution` that went with them.
- The builder-document lookup had a private `_get_doc_or_404` in `builder.py` that
  `versions.py` was importing **by its private name across modules**, while `projects.py` and
  `triggers.py` re-typed its three filters — including `is_active`, the one easiest to omit,
  and the one whose absence would resurrect a deleted document.

Both helpers moved to `app/api/v2/_access.py`, one layer up from the package they were
private to, because that is where their callers turned out to live. 170 → 164 queries; the
rest are single reads with no repeated shape, which is opportunistic cleanup for real rather
than a name for work left undone.

**D-16 · ✅ Resolved (2026-07-29) — 16 entries: 6 were never debt, 7 moved down or died, 3 became host ports.**
The inventory frozen in contract 7 turned out to hold two different things, and reading them
as one list is what made D-16 look like a day of untangling.

**Six were the contract measuring by directory.** `BOUNDED_CONTEXTS.md` puts routes inside
the domain tree deliberately — a bounded context is a vertical slice, adapters through
routes — so a solver route asking for `CurrentUser` or `DBSession` is that slice using the
API layer it belongs to, not a layer inversion. Owner's call (2026-07-29): make it a stated
rule instead of a listed exception. The contract now allows `app.domains.*.routes.* ->
app.api.deps` by pattern, with the reasoning in the file the build reads.

**Two were real, and not of the kind the list suggested.** `file_io` and `templates` imported
`_enqueue_async_solve`, `_wait_for_task` and `_shape_sync_result` — private functions of the
`solve.py` *endpoint module*, by their underscore names, across a package. Those three are
not endpoint code: they are the one path ADR-007 requires every solve to ride, whoever asks
for it. They now live in `app/api/v2/solve_pipeline.py` with names of their own, together
with what only they used (tier caps, the sync-wait semaphore, the multi-objective enqueue,
the solution filter). `solve.py` drops from 1407 lines to 692, and what the domain consumes
is a declared API rather than another module's privates — which is why the contract names
that module explicitly instead of opening up `app.api` wholesale.

**Then eight more went (2026-07-29), once the owner settled what the domain is for**: the
solver moves to its own repository, and JAOT must take any solver — today's, one written
there, a GPU one later — by writing an adapter and nothing else. That makes every upward
import a question with one right answer: *could this run outside JAOT?*

- **Provenance** (`ORIGIN_*`, `ExecutionSource`) was two string constants. To
  `app/shared/constants/`.
- **Problem validation** moved into the domain with `InvalidProblemError`; the API keeps a
  thin translation to 400 with the same message. A packaged solver can now check its input
  without importing FastAPI.
- **Time limits** stopped taking a `Session` to answer a question about seconds. The values
  come in as numbers; `app/api/v2/_solver_limits.py` is where knowing about
  `platform_settings` lives.
- **The solver thread pool was dead code**, and with it `SOLVER_POOL_SIZE` — see below.

**Template routes moved instead of being patched.** `templates.py` resolved a template id —
which may answer with a YAML template *or a published marketplace listing* — and logged the
result to platform analytics. A solver packaged on its own has no marketplace to search, so
this was never domain code: it now lives at `app/api/v2/routes/solve_templates.py`, mounted
under the same `/solve` prefix with the paths unchanged. What the domain does own, rendering
a resolved template into a problem, stays as `template_engine`.

### The last three · ✅ Resolved (2026-07-29) — the domain declares ports, JAOT registers them

All three sat **inside the Celery tasks that run every solve**: `scenario_tasks` reading six
`SENSITIVITY_*` settings in the worker, and `solve_tasks` telling notifications (×2) and the
marketplace about outcomes. They are now the two ports of `app/domains/solver/ports.py` —
a scenario-budget reader and a `SolveEventSink` (`listing_executed` / `solve_completed` /
`solve_failed`) — and `app/tasks/solver_ports.py` is JAOT's side: it binds them to
`PlatformSettingsService`, `NotificationService` and `marketplace_fusion`, and registers on
import. That is the shape that lets a solver in its own repository run under a different
host — and why moving `PlatformSettingsService` into `app/shared/` was never the fix: a
separate repository does not share `app/shared/` either.

**The two-boot risk, and how it is held.** Registration must happen in *two* processes — the
API (which reads the budget at enqueue to derive kill limits) and the Celery worker (which
runs everything else). The design the risk warned about — fall back to defaults if a boot
forgot to register — is exactly what was NOT built: an unregistered port **raises**, so a
missing registration fails every solve loudly instead of shipping wrong budgets or dropping
notifications in silence. The API registers in the lifespan; the worker's registration point
is the Celery `include` list, which imports `app.tasks.solver_ports` at boot exactly like a
task module. Contract tests pin the include entry and the raise-not-default behaviour; the
end-to-end check (a real marketplace solve through the running stack: notification row
written, listing counters moved, what-if batch under the platform budget) verified the two
processes really do both register.

**What the end-to-end check caught: solve notifications had never been delivered.** The
first real solve came back half green — counters moved, notification table empty — while
the worker logged *"Created notification"*. Two defects, one swallow: the notification
writer only flushes and the task committed *before* notifying, never after, so the row died
with the worker's session on every solve since the path existed (D-24's lesson, one process
over); and the failure path read `model.display_name`, a column that lives on the *listing*,
so an `AttributeError` fell into the log-and-continue handler and the failed-solve
notification never went out at all. The suite could not see either: in tests the session
outlives the task. Fixed by committing the notification after the solve's own terminal
commit and naming the model as the success path does; two regression tests now read back
through a *different* session after the worker's is closed, and fail with either defect
restored.

**A control that did nothing (2026-07-29).** `app/domains/solver/services/pool.py` built a
`ThreadPoolExecutor` "shared across all synchronous solve paths" — and ADR-007 moved every
in-request solve to the queue, leaving the module with **no callers at all**. Its only
reason to exist was reading `SOLVER_POOL_SIZE`, which therefore configured nothing, while
the admin panel offered it with a help text explaining when a change would take effect.
Module, setting, row (`20260729_drop_solver_pool_size`) and the seven tests that kept it
alive — four of which only asserted that the database returned a number — all gone. The
23 settings §1.9 retired had a twenty-fourth.

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
