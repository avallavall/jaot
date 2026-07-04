# ADR-007 — Async-only executions: one pipeline, one writer, one credit model

- **Status:** Accepted (2026-07-04)
- **Spans:** the "consolidation of executions" phase (pre-P1.5 by explicit order decision).
- **Related:** ADR-006 (ModelProject unification — P1.5 depends on this phase), the
  solve-contract-drift invariant, the executions fix-wave (`c877ac6`, the first step of this
  direction), W15/F-01 Celery time limits, the execution reaper.

## Context

Solving grew **two parallel execution stacks**. The async pipeline (`POST /solve/async` →
Celery `solve_async` → `ModelExecution`) powers the studio, Live Solve, scenarios and durable
sessions. Beside it, **six synchronous entry points** still solve inside the HTTP
request-response: `POST /solve`, `POST /solve/multi-objective`, template solve, import-and-solve,
`POST /projects/{id}/solve`, and the marketplace `execute_model` (dual-mode) — plus the trigger
task solving inline. The consequences, all observed in production or live testing:

- **≥6 independent `ModelExecution` writers** (orchestrator, `execute_model` inline, the
  `solve_async` route + worker pair, `solve_model_async`, `trigger_solve_task`, the reaper) —
  the direct cause of the "pending zombies / empty detail" class of bugs.
- **4 credit-deduction models** (orchestrator pre-pay+refund; async pre-pay-before-enqueue;
  `execute_model`-sync and triggers deduct-after-solve) with divergent failure semantics.
- **Solve-contract drift by construction**: every behavior change must be replicated across
  entry points that share no pipeline (the recurring bug class this codebase documents).
- Sync solves block API workers for the whole solve, cap solve length at HTTP timeouts, and
  can't stream progress; long solves are effectively async-exclusive features.
- The scenario launcher compiles client-side and uploads ~30MB flat problems through the
  browser because the solve contract has no server-side compile seam (patched today at the
  proxy body-cap; the root fix belongs to the solve contract).

The MCP surface (all 6 solve tools) is entirely synchronous — the canonical
"I just want the answer" caller.

**Order decision (owner, 2026-07-04):** this phase runs BEFORE the P1.5 marketplace fusion, so
the fusion migrates ONE consolidated pipeline instead of two (the sync `execute_model` path
would otherwise be carefully migrated and then deleted).

## Decision

1. **One execution mechanism.** Every user solve is enqueued to Celery and recorded as a
   `ModelExecution` row before it runs. The universal `solve_async` task is canonical.
   `solve_model_async` (marketplace contract: template render + counters + notification)
   remains temporarily as a thin sibling on the SAME writer and credit model; it is absorbed
   when P1.5 folds the marketplace onto `ModelProject`. `trigger_solve_task` stops solving
   inline and enqueues the canonical task.

2. **One `ModelExecution` writer.** A single module owns every state transition
   (insert-pending → running → completed / failed / cancelled, terminal states win). The
   routes, both workers, the trigger path and the reaper all call it. No other code touches
   `ModelExecution` status/result/credits columns.

3. **One credit model: pre-pay + refund.** Credits are deducted before enqueue (workspace pool
   first, then org; 402 on shortfall) and refunded on solver-level error, task exception,
   enqueue failure, unknown solver, cancellation policy, or reaping — under the existing
   idempotent refund keys. The two deduct-after-solve paths (`execute_model` sync, triggers)
   migrate to this model; their "no charge on error" behavior is preserved as refund-on-error.

4. **`?wait=true` for "just give me the answer" callers.** `POST /solve/async?wait=true`
   blocks server-side (a sync `def` handler in the threadpool doing a bounded
   `AsyncResult.get`) and returns the **exact synchronous `OptimizationResult` contract**:
   the double-nested envelope is flattened, and `execution_id`, `credits_used`,
   `credits_remaining` are injected (the worker's result carries schema defaults for these).
   Errors map back to the sync semantics (solver error → `status=error` result; 402/408/422
   raised as before). On wait-timeout the response degrades to `202 {task_id, poll_url, ...}`.
   The wait budget is capped below the frontend proxy timeout (120s) at **100s**.

5. **The legacy sync endpoints keep their CONTRACTS but become wrappers.** `POST /solve`,
   multi-objective, template solve, import-and-solve and `POST /projects/{id}/solve` delegate
   to enqueue + wait internally — same request/response schemas, same Idempotency-Key
   behavior, same error codes. External API users and the 8 sync frontend call sites keep
   working unchanged; the UI migrates to visible-progress async incrementally. The
   **synchronous execution mechanics behind them die** (`SolveOrchestrator.solve_single`'s
   in-request path, `execute_model`'s inline solve). Multi-objective enqueues as one task
   (the scalarization loop runs in the worker) and returns `MultiObjectiveResult` via the
   same wait machinery.

6. **`execution_id` is first-class in the async contract.** `POST /solve/async` responses gain
   `execution_id` (`exe_…`) alongside `task_id` (additive). History queries and refund keys
   keep their current identities during this phase.

7. **MCP stays synchronous in shape.** The 6 solve operation_ids are unchanged; they ride the
   wrapped endpoints (wait-backed) and gain long-solve robustness via the 202 degradation.

8. **Out of scope / unchanged:** `/solve/validate`, previews, and on-demand
   infeasibility-analysis stay synchronous (they don't run user solves); the execution reaper
   STAYS (it becomes the single backstop for an all-pending world) and is simplified once the
   writer/credit unification lands; server-side scenario compile (`source + dataset_id` on the
   solve contract) is designed here as the seam but may ship as the last slice.

9. **Timezone normalization.** `ModelExecution` (and sibling execution-surface) datetime
   columns move to `timezone=True` via an in-place `ALTER ... USING ... AT TIME ZONE 'UTC'`
   migration (values are already UTC; verified cheap on PG18), the reaper's
   `.replace(tzinfo=None)` workaround is removed, and the frontend's `apiDate()` keeps working
   (it only assumes UTC when the offset is absent).

## Consequences

- P1.5 later migrates one async pipeline; `execute_model` is a thin wrapper by then.
- Parity is enforced by CONTRACT-TESTs (sync contract == wait-backed result, field by field)
  written BEFORE the wrappers land — the phase's slice 0.
- One writer + one credit model turn the recurring "zombie execution / phantom charge" bug
  classes into single-point fixes.
- API workers stop burning threads on long solves except bounded waits; every solve gains
  progress streaming, cancellation, durable history and dataset provenance for free.
- Risk concentrates in credit correctness during the writer transition (guarded by existing
  idempotency keys + CONTRACT-TESTs) and in the wait-wrapper's error mapping (pinned by the
  parity tests).

## Implementation slices (each gated, committed separately)

- **S0** Parity CONTRACT-TEST harness (sync `/solve` vs wait-backed result, field-level).
- **S1** `?wait=true` on `/solve/async` (threadpool, bounded get, contract mapping, 202 fallback).
- **S2** `POST /solve` → async-under-the-hood (Idempotency-Key preserved; warm-start parity).
- **S3** Single writer module + pre-pay/refund in `execute_model` and triggers.
- **S4** Template / import / project-solve / multi-objective onto the pipeline via wrappers.
- **S5** Frontend sync call sites → wait-backed or visible-progress async; MCP verified.
- **S6** Timezone migration + reaper simplification + delete dead sync mechanics.
- **S7 (optional tail)** Server-side scenario compile: solve accepts `dsl_source + dataset_id`.
