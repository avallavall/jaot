# Technical debt

**What this file is for: debt that is still open.** A closed entry moves to the index at the
bottom — one line, with the date. Its reasoning, its measurements and the bugs it turned up
are in the commit that closed it and in [CHANGELOG](../CHANGELOG.md); repeating them here
turned this file into 500 lines of post-mortem nobody could act on.

**Nothing is open.** Every entry below is closed or rejected.

---

## Closed

Full reasoning in the commit that closed each one, and in the CHANGELOG.

| # | Debt | Closed |
|---|------|--------|
| D-01 | 79 compatibility shims in `app/core/` | ✅ `9357e9dd` |
| D-02 | `import-linter` contracts consolidated 6→5 | ✅ |
| D-03 | Double refund on cancel (later moot — ADR-008 removed credits) | ✅ `20260317_add_credit_idempotency_constraint` |
| D-04 | IDOR in `GET /models/async/{task_id}` | ✅ |
| D-05 | Solver refusals worked as a licence oracle | ✅ 2026-07-26 |
| D-06 | `celery_beat` booting through the shim | ✅ (by D-01) |
| D-07 | `CeleryWorkerDown` alert on the pre-rotate container name | ✅ |
| D-08 | Flaky rate-limiter fixture | ✅ `9357e9dd` |
| D-09 | Server 180 commits behind, CI red 7 days | ✅ |
| D-10 | `/health` blocked the loop 100 ms per call (`psutil`) | ✅ `7a7623c` |
| D-11 | CI had no security gate at all | ✅ `pip-audit` + `bandit` + `npm audit` |
| D-12 | 113 `async def` endpoints issuing sync DB calls on the loop | ✅ `27c1ae8` (ADR-009) |
| D-13 | 7 handlers doing genuinely heavy work on the loop | ✅ `2b81868` |
| D-14 | 23 foreign keys with no index (18 fixed, 5 deliberately skipped) | ✅ `20260726_index_fks` |
| D-15 | No contract on the vertical import direction | ✅ contract 7 |
| D-16 | Upward imports from `domains` — 6 were never debt, 7 moved, 3 became ports | ✅ 2026-07-29 |
| D-17 | 44 endpoints (not 55) with no `response_model`; found 2 bugs | ✅ 2026-07-30 |
| D-19 | Route-level queries: audited all 58 unfiltered, **all correct**; 2 helpers consolidated | ✅ 2026-07-29 |
| D-20 | Prod compose justified API limits with a rationale ADR-007 retired | ✅ `f4dd487` |
| D-21 | Capacity limits inherited from the paid tiers (0 = unlimited now) | ✅ 2026-07-26 |
| D-22 | 98 orphaned `platform_settings` rows (+3 Featurebase in prod) | ✅ `20260728_prune_orphan_settings`, `20260731_prune_featurebase` |
| D-23 | Rate limits read from a mirror on `organizations` | ✅ 2026-07-31 — never needed the schema change |
| D-24 | Three surfaces wrote nothing: `recent_models`, view events, detached principal | ✅ 2026-07-28 |
| D-18 | 118 `Depends(get_db)` migrated to the `DBSession` alias; the alias moved to break a cycle | ✅ 2026-08-01 |
| D-25 | Admission bounded to the pool, `pool_timeout` 30s→5s, health off the queue, pool gauges + alerts | ✅ 2026-08-01 (step 4 became D-27, rejected) |
| D-26 | Contract-release: legacy tables + 6 FK columns + 6 credit columns dropped, `access_count` → integer; found reviews had lost their uniqueness guarantee | ✅ `20260801_contract_release` |
| D-30 | The shared rate limiter takes a `cost`, so a comparison the quota cannot cover is refused without spending any of it | ✅ 2026-08-19 |
| D-33 | The stored adoption counter dropped; every surface counts through `adoption_query`, with an index for the join | ✅ `20260824_drop_total_activations` |
| D-32 | A comparison's columns stopped copying its problem; `ModelExecution.problem_data` reads the parent's snapshot. Cleared 59 MB of a 216 MB table on the development database | ✅ `20260824_comparison_copies` |
| D-36 | The reaper settles a stale `TriggerRun` too, so an abandoned run stops blocking its own cron schedule | ✅ 2026-08-25 |
| D-28 | The `fastapi<0.137.0` ceiling measured `len(app.routes)`, which 0.137 stopped being a route count. Nothing was broken: unpinned, and the two tests that read that list now issue a request instead | ✅ 2026-08-25 |
| D-29 | The TTL-cache-plus-single-flight pattern extracted into `app/shared/utils/ttl_probe.py`. Four copies disagreed on what a caller does while a refresh runs; that is now an argument every caller names | ✅ 2026-08-26 |

**The 2026-04-18 comparative audit** (58% essential / 42% accidental complexity, the LOC
tables) and the **2026-07-26 backend audit** that produced D-10…D-19 are in
[`02-backend/07-audit-2026-07-26.md`](02-backend/07-audit-2026-07-26.md) and
[ADR-009](08-decisions/ADR-009-sync-endpoints-with-a-sync-session.md).

**Rejected, with reasons:** PgBouncer in transaction mode (owner, 2026-09-01 — see below),
microservices (owner, 2026-07-25), a dynamic `auto_router` tree
(its reason slugs are public API contract; it does consult capabilities when substituting for
a solver this server does not have, under a slug that names none), and an async-SQLAlchemy
migration (ADR-009 buys the same for a fraction of the cost).

---

## Rejected · PgBouncer in transaction mode (was D-27)

Registered on 2026-08-01 as the fourth step of D-25, deferred twice, and **dropped for good by
the owner on 2026-09-01.** It is not deferred work any more; nobody should re-open it as debt.

The connection budget it existed to raise is documented where it is enforced:
[`05-celery-queue-workers.md`](05-infrastructure/05-celery-queue-workers.md#pool-sizes). It fits
inside `max_connections = 100` and it was sized on purpose. The gauges
`jaot_db_pool_checked_out` and `jaot_db_pool_capacity` say when it stops fitting.

PgBouncer would put a container in the path of every query. It also breaks two things this
codebase relies on, and both would have to be re-solved before adopting it:
`connect_args={"options": "-c timezone=utc"}` (session state does not survive transaction
pooling) and `pool_pre_ping`. If the pool gauges ever hit the ceiling, the cheaper answers come
first: raise `max_connections`, or cut a worker's pool to what its concurrency can use.
