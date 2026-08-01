# Technical debt

**What this file is for: debt that is still open.** A closed entry moves to the index at the
bottom — one line, with the date. Its reasoning, its measurements and the bugs it turned up
are in the commit that closed it and in [CHANGELOG](../CHANGELOG.md); repeating them here
turned this file into 500 lines of post-mortem nobody could act on.

Ordered by benefit ÷ effort.

| # | Debt | Impact | Effort |
|---|------|--------|--------|
| D-25 | The API admits four times more concurrent work than the DB pool can serve, and the health check queues behind it | Medium-high (availability under load) | 0.5 day for the first two steps |
| D-26 | Contract-release: legacy schema `DROP`s, `favorite.py` on `Column()`, `access_count` stored as text | Low-medium (blocks reliable `--autogenerate`) | Needs its own release window |
| D-18 | 118 `Depends(get_db)` alongside 118 `DBSession` — the project rule mandates the alias | Low (consistency) | 0.5 day, mechanical |

---

## D-25 · Admission control is wider than the database pool

**Measured 2026-08-01.** Endpoints are synchronous by design (ADR-009 moved them off the
event loop on purpose), so each runs in the AnyIO threadpool — **40 tokens per process, the
default, never tuned**. Against that:

| | Processes | DB pool per process | Threads per process | Ratio |
|---|---|---|---|---|
| Local | `WORKERS=1` | 20+10 = 30 | 40 | 1.3 : 1 |
| **Production** | `WORKERS=4` | 5+5 = **10** | 40 | **4 : 1** |

The threadpool is therefore a queue that admits four times what the pool can serve. Request 11
on a worker waits out SQLAlchemy's `pool_timeout` (**30 s, unset, so the default**) and then
500s. Workers are independent, so one hot worker fails while the other three idle.

**The amplifier:** `/health` and `/health/status` are `def` *and* take a DB session
(`app/api/v2/health.py`), so under saturation the health check queues with everything else →
Docker marks the container unhealthy → restart → in-flight requests die and the load lands on
the remaining workers. That is how "slow" becomes "down".

**Connection budget today** (`max_connections = 100`): API 4×10 = 40, Celery 4 containers ×10
= 40, beat 10 → **≈ 90 in the worst case**. It fits, and it was clearly sized on purpose, but
there is ~10% headroom and every new worker or queue re-opens the arithmetic.

**Not yet decided; recommended order:**

1. **Expose the pool.** `engine.pool.status()` reaches no metric today, so this failure is
   invisible until it 500s. A gauge for in-use / overflow / waiting, and an alert on pool wait
   time > 0.
2. **Make admission coherent.** Bound the threadpool to the pool size per process, and drop
   `pool_timeout` to ~5 s. Turns "stall 30 s then 500" into backpressure or a fast failure.
3. **Take health out of the queue.** `async def`, no DB session — this is the cheapest fix for
   the worst failure mode (the restart cascade).
4. **PgBouncer in transaction mode**, when there are real users or more workers. It decouples
   app concurrency from Postgres backend count, so pools can be generous without renegotiating
   `max_connections`. Caveats to check first: `connect_args={"options": "-c timezone=utc"}` and
   `pool_pre_ping`.

**Explicitly not the answer:** converting endpoints to `async def`. ADR-009 moved this work off
the loop deliberately (import/export/validate is heavy SCIP work); putting it back would trade
a 500 under load for a total stall.

> The QA sweep that surfaced this ran 4 Playwright agents against **local** (`WORKERS=1`,
> pool 30). A page load fires 5–15 API calls, so that was ~40 concurrent requests — a load
> test, not four users. The defect is real; the "four users broke production" reading is not.

---

## D-26 · Contract-release

Additive-only migrations make these release-shaped, not refactor-shaped: rollback restores
images, not schema, so an image that still selects a dropped column crashes. They need their
own window, and until they land `alembic --autogenerate` stays unreliable.

- Legacy `DROP`s: `model_catalog`, `organization_models` and the ADR-008 billing columns.
- `app/models/favorite.py` still uses legacy `Column()` (11 of them) instead of
  `Mapped` / `mapped_column`.
- `access_count` is a `String` column holding a number. The schema converts it on the way out
  and the increment casts through integer, so nothing is broken — the column is.

---

## D-18 · `Depends(get_db)` vs the `DBSession` alias

118 of each as of 2026-08-01, so the migration stalled halfway. Purely a consistency rule
(`app/CLAUDE.md`); no behaviour depends on it. Mechanical, and safe to do opportunistically
whenever a route is touched for another reason.

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

**The 2026-04-18 comparative audit** (58% essential / 42% accidental complexity, the LOC
tables) and the **2026-07-26 backend audit** that produced D-10…D-19 are in
[`02-backend/07-audit-2026-07-26.md`](02-backend/07-audit-2026-07-26.md) and
[ADR-009](08-decisions/ADR-009-sync-endpoints-with-a-sync-session.md).

**Rejected, with reasons:** microservices (owner, 2026-07-25), a dynamic `auto_router` (its
reason slugs are public API contract), and an async-SQLAlchemy migration (ADR-009 buys the
same for a fraction of the cost).
