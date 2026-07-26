# ADR-009 — Endpoints that use the synchronous session are declared `def`, not `async def`

**Status:** Accepted (owner decision, 2026-07-26 — "empezamos la auditoría"; implemented the
same day for the mechanical group, see the Implementation note at the end)
**Context:** post-v3.2, before v4.0 (in-repo solver). Companion to
`docs/ARCHITECTURE/02-backend/07-audit-2026-07-26.md` (findings F-01, F-02).

## Context

JAOT talks to PostgreSQL through a **synchronous** SQLAlchemy session: `create_engine` +
`sessionmaker`, handed to routes by a plain `def get_db()`. That is a deliberate, working
choice — SQLAlchemy 2.0 sync sessions are simple to reason about, and Celery does the heavy
lifting for anything long.

FastAPI treats the two endpoint flavours differently:

- `def` → runs in a **threadpool**; blocking I/O inside it costs one thread.
- `async def` → runs **on the event loop**; blocking I/O inside it stalls every other request
  that worker is serving until it returns.

The audit found that 109 endpoints are `async def` *and* issue synchronous DB calls. **99 of
them contain no `await` whatsoever** — they are `async` by copy-paste, not by need. Production
runs 4 uvicorn workers, so each blocked loop takes a quarter of the server's concurrency with
it for the duration of the query.

The codebase already knows the right answer where somebody thought about it. `solve.py` says
so in its own comments:

```python
def solve_optimization_problem(  # def: blocks on the queued result (ADR-007 S2)
def validate_problem_endpoint(   # sync ON PURPOSE -> threadpool (CPU-bound, no awaits)
def solve_optimization_problem_async(  # sync ON PURPOSE -> FastAPI threadpool
```

That reasoning was never written down as a rule, so it did not travel to the other 109
endpoints. This ADR writes it down.

## Decision

**An endpoint that touches the synchronous session, or does any other blocking work, is
declared `def`. `async def` is reserved for endpoints that actually `await` something.**

Concretely:

1. **`async def` + no `await` in the body → `def`.** Mechanical, behaviour-preserving.
   (99 endpoints today.)
2. **`async def` + a genuine `await` + synchronous DB work → keep `async def`, move the DB
   work off the loop** with `run_in_threadpool` (or an equivalent). Case by case, because the
   awaits are real (`await file.read()`, `await _validate_image(file)`). (10 endpoints today.)
3. **New endpoints** follow rule 1 by default. Reviewers treat an `async def` with no `await`
   as a defect.

### What this ADR does NOT decide

It does **not** migrate the project to async SQLAlchemy. That would touch every query in the
backend to arrive at the same concurrency this rule achieves by changing a keyword. If async
sessions are ever wanted, that is a separate decision with its own ADR.

## Consequences

**Good**
- A slow query stops being a server-wide stall and becomes one busy thread.
- The rule is checkable: "`async def` with no `await`" is a grep, and could become a
  pre-commit or CI check so the drift cannot come back.
- Zero behaviour change: FastAPI's threadpool path is the same one the solve endpoints and
  every `def` endpoint already use in production.

**Costs / risks**
- The threadpool is bounded (anyio's default is 40 threads). Moving ~100 endpoints onto it
  raises thread pressure; each concurrent request also holds a DB connection, so
  `DB_POOL_SIZE` + `DB_MAX_OVERFLOW` must be sized against it. This is the one thing to
  verify under load rather than assume — the pool is already the real limit today, but the
  shape of the contention changes.
- ~109 signatures change in one pass. The diff is large but shallow, and the test suite
  (3,809 backend tests) exercises these endpoints through the real app.

## Alternatives considered

- **Leave it.** Defensible while traffic is low — nothing is on fire. Rejected as the default
  because the cost of fixing it grows with every endpoint added, and v4.0 (in-repo solver) is
  about to add the largest batch of new code the project has seen.
- **Migrate to async SQLAlchemy.** Rejected: same benefit, order-of-magnitude more work and
  risk, and it would have to land while the solver work is in flight.
- **Wrap `get_db` so it hides the blocking.** Rejected: it does not help — the blocking is in
  the query calls themselves, not in acquiring the session.

## Verification

Before/after on the same box, since the claim is about concurrency and not about a single
request: N concurrent calls to an endpoint with a deliberately slow query, measuring the
latency of an *unrelated* fast endpoint during the burst. Today the fast one degrades with N;
under this rule it should stay flat until the threadpool or the DB pool saturates.

## Implementation note (2026-07-26)

Rule 1 is **done**: 113 route handlers went from `async def` to `def` across 26 files
(110 found by scanning `app/`, plus 3 that became mechanical once the awaits below were
removed). Nothing else changed — same bodies, same dependencies, same responses.

Three handlers were calling *another handler* directly with `await`
(`update_notification_preference` → `get_notification_preferences`, and the two `by-slug`
profile routes → their `..._public_profile` counterparts). Those awaits are gone, since the
callees are now plain functions. Endpoint-calling-endpoint is itself a smell — the shared
logic belongs in a service — but that is a separate change and is left alone here.

**Deliberately NOT converted (6, rule 2 / D-13):** the four `explain_*` SSE endpoints in
`llm.py` and the two `export_*` handlers in `domains/solver/routes/file_export.py`. They
return `StreamingResponse`, so whether they may leave the loop needs to be reasoned about one
by one rather than swept.

**Verified** by the full suite (3,785 passed + 204 slow/load, 0 failed) and by driving the
real app: `/health`, both `by-slug` profiles, the notification-preference `GET`/`PUT` pair
(the place an `await` was removed), and an async solve followed by its polling endpoint —
`get_async_solve_status`, the highest-traffic handler in the batch — which returned
`completed` / `optimal` as before.

The threadpool-vs-DB-pool question in "Consequences" stands: `DB_POOL_SIZE` defaults to 20
(+10 overflow) per process against anyio's 40 threads, so under saturation the DB pool is the
binding constraint, not the threadpool. That was already true for every `def` endpoint,
including the solve facade; this change widens how many endpoints reach it. Worth measuring
under load before assuming it is fine.
