# Technical debt

**What this file is for: debt that is still open.** A closed entry moves to the index at the
bottom — one line, with the date. Its reasoning, its measurements and the bugs it turned up
are in the commit that closed it and in [CHANGELOG](../CHANGELOG.md); repeating them here
turned this file into 500 lines of post-mortem nobody could act on.

Ordered by benefit ÷ effort.

| # | Debt | Impact | Effort |
|---|------|--------|--------|
| D-28 | `fastapi<0.137.0` is pinned around a fragility of ours, not around FastAPI | Silent: the app would boot "healthy" with 228 routes missing | A bounded investigation |
| D-27 | PgBouncer in transaction mode, once there are real users or more workers | Low today, rising with load | Needs an infra window |
| D-29 | The TTL-cache-plus-single-flight pattern is written three times, and the three disagree | Low: each one works; the next copy is where it stops working | An afternoon, once a fourth caller needs it |

---

## D-27 · PgBouncer, when the connection budget gets tight

The last step of D-25, deliberately deferred: the first three closed the failure mode, this one
raises the ceiling.

**Connection budget today** (`max_connections = 100`): API 4×10 = 40, Celery 4 containers ×10
= 40, beat 10 → **≈ 90 in the worst case**. It fits, and it was sized on purpose, but there is
~10% headroom and every new worker or queue re-opens the arithmetic.

PgBouncer in transaction mode decouples app concurrency from the Postgres backend count, so
pools can be generous without renegotiating `max_connections`. Two caveats to check before
adopting it, both load-bearing here: `connect_args={"options": "-c timezone=utc"}` (session
state does not survive transaction pooling the way it survives a session) and `pool_pre_ping`.

Not urgent while the platform is quiet, and the gauges from D-25 now say when it stops being
quiet: watch `jaot_db_pool_checked_out / jaot_db_pool_capacity`.

---

## D-28 · The FastAPI pin covers something of ours

Two pins look alike and are not. **`mcp>=1.12.0,<2` is correct and is not ours**: `fastapi-mcp`
0.4.0 calls `Server(name, description)` and 2.0 removed that argument, so the ceiling stays
until `fastapi-mcp` ships a compatible release. **`fastapi<0.137.0` is a different animal.**

Measured 2026-07-31 in a throwaway container, without touching the repo:

| fastapi | `api_v2_router.routes` | `app.routes` |
|---|---|---|
| 0.136.1 (current) | populated | **236** |
| 0.141.1 | **27** | **8** |

**Nothing raises.** The app boots looking healthy — MCP mounted, Prometheus exposed — with 228
routes that simply do not exist. That is the worst available failure mode: a deploy on that
version serves 404 for almost everything with a green health check.

The useful clue is that the intermediate router already arrives with 27 of ~228, so it is not
`app.include_router` failing but composition losing pieces earlier, inside `app/api/v2/router.py`.
The mounting is entirely idiomatic, which points at import order or cycles: a sub-router composed
while its module is still half-imported arrives empty, and on 0.136 the order happens to work.

If that is confirmed, the pin is not protecting us from FastAPI — it is protecting us from
ourselves, and it gets more expensive with every release that passes. Bounded investigation:
reproduce on 0.141 and bisect which `include_router` loses its routes.

⏸️ **Deliberately asleep** (owner, 2026-07-31): *"if it works like this, leave it"*. The numbers
are here for whoever picks it up. Do not reopen unprompted.

---

## D-29 · The same TTL cache is written three times, and the three disagree

Three places cache an expensive probe in process memory behind a TTL and a lock, each one
written from scratch:

| Where | TTL | What a caller does when the cache is cold |
|---|---|---|
| `api/v2/health.py` (`MAINTENANCE_MODE`) | 10 s | Non-blocking `acquire`; a loser serves the stale value. Only the very first probe waits, because there is no stale value to serve yet |
| `domains/solver/services/worker_health.py` (Hexaly queue) | 15 s | Double-checked locking: a loser blocks, then finds the cache filled |
| `services/llm/cost_tracking.py` (monthly LLM spend) | 60 s | **No single flight at all.** The lock only guards reading and writing the tuple, so N callers that arrive on an expired cache all run the month-cost query |

Each one is defensible where it sits, and the reasoning is in the comments: health must never
block on a saturated pool, the Hexaly probe broadcasts to the whole fleet, the spend query is
cheap enough that a stampede of a few is harmless.

What makes this debt is that the differences are invisible from the outside. The fourth caller
that needs this will copy whichever file it opens first, and there is no shared helper that
makes the choice explicit. Worth extracting when that fourth caller shows up, not before.

Recorded 2026-08-13. It had been sitting in an internal QA note since 2026-08-01, which is
the wrong place for open debt.

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
| D-25 | Admission bounded to the pool, `pool_timeout` 30s→5s, health off the queue, pool gauges + alerts | ✅ 2026-08-01 (step 4 → D-27) |
| D-26 | Contract-release: legacy tables + 6 FK columns + 6 credit columns dropped, `access_count` → integer; found reviews had lost their uniqueness guarantee | ✅ `20260801_contract_release` |

**The 2026-04-18 comparative audit** (58% essential / 42% accidental complexity, the LOC
tables) and the **2026-07-26 backend audit** that produced D-10…D-19 are in
[`02-backend/07-audit-2026-07-26.md`](02-backend/07-audit-2026-07-26.md) and
[ADR-009](08-decisions/ADR-009-sync-endpoints-with-a-sync-session.md).

**Rejected, with reasons:** microservices (owner, 2026-07-25), a dynamic `auto_router` (its
reason slugs are public API contract), and an async-SQLAlchemy migration (ADR-009 buys the
same for a fraction of the cost).
