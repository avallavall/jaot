"use client";

import { useEffect, useRef } from "react";
import { useStore } from "zustand";
import { api } from "@/lib/api";
import { useExecutionWebSocket } from "@/hooks/useWebSocket";
import { extractProgressHistory, type ProgressPoint } from "@/lib/result-utils";
import type { AsyncSolveResultEnvelope, ProjectExecutionItem, SolveResult } from "@/lib/types";
import type { LastRunStatus, ModelProjectStore } from "./createModelProjectStore";
import { toProgressPoint, type SolveProgressEvent } from "../panels/solve/live-solve-metrics";

/**
 * The completed async-solve status nests the Celery task envelope under `result`,
 * so the actual solver result is `result.result`. Fall back to `result` itself.
 *
 * Routing telemetry (`solver_used`, `auto_route_reason`, `warning`) is HOISTED by
 * the async-status endpoint to the TOP level of the response (and the envelope) —
 * it is NOT inside the inner solver result — so merge it back onto the returned
 * result. Without this an `auto` solve shows "auto" instead of the solver that
 * actually ran (e.g. SCIP).
 */
function unwrapSolveResult(status: {
  result?: unknown;
  solver_used?: string;
  auto_route_reason?: string;
  warning?: string;
}): SolveResult | null {
  const envelope = status.result as AsyncSolveResultEnvelope | SolveResult | undefined;
  if (!envelope) return null;
  const env = envelope as AsyncSolveResultEnvelope;
  const base = ((env.result ?? envelope) as SolveResult) ?? null;
  if (!base) return null;
  return {
    ...base,
    solver_used: status.solver_used ?? env.solver_used ?? base.solver_used,
    auto_route_reason: status.auto_route_reason ?? env.auto_route_reason ?? base.auto_route_reason,
    warning: status.warning ?? env.warning ?? base.warning,
  };
}

/** A solve that the server still considers in-flight — re-attachable by task id. */
const ACTIVE_STATUSES = new Set(["pending", "running"]);
/** Map a finished execution status to the store's terminal "last run" status. */
const TERMINAL_STATUS: Record<string, LastRunStatus> = {
  completed: "completed",
  failed: "failed",
  cancelled: "cancelled",
  timeout: "timeout",
};

/**
 * Decide what a reconciled latest execution means for the store: re-attach a
 * still-running async solve by its task id, or surface a finished one as the
 * "last run". Pure so it can be unit-tested without React.
 */
export function applyReconciledExecution(
  store: ModelProjectStore,
  latest: ProjectExecutionItem | undefined
): void {
  const s = store.getState();
  // Never clobber a solve the user started (or another reconcile attached) meanwhile.
  if (s.solveSession.status !== "idle") return;
  if (!latest) return;

  if (ACTIVE_STATUSES.has(latest.status) && latest.is_async && latest.celery_task_id) {
    // Re-attach: feed the server's task id to the same machinery a fresh solve
    // uses. The poll + WS below resume from wherever the solve actually is. The
    // server's start time (not "now") keeps the header's "started Xm ago" honest
    // for a solve that has really been running for hours.
    s.startSolveSession(
      latest.celery_task_id,
      latest.solver_name ?? null,
      latest.started_at ?? latest.created_at ?? null
    );
    return;
  }

  const terminal = TERMINAL_STATUS[latest.status];
  if (terminal) {
    if (s.lastRun?.executionId === latest.id) return; // already surfaced — avoid re-render churn
    s.setLastRun({
      executionId: latest.id,
      status: terminal,
      objectiveValue: latest.objective_value ?? null,
      solverName: latest.solver_name ?? null,
      finishedAt: latest.completed_at ?? latest.created_at ?? null,
    });
  }
}

/**
 * Drives the async-solve session from the canonical store. Mounted at the
 * PROVIDER / layout level (not in `SolvePanel`) so it keeps polling completion and
 * accumulating live points even while the user is on another tab — the running
 * solve is never lost on a tab switch.
 *
 * On mount it RECONCILES from the server (the solve runs server-side; its truth
 * lives in `ModelExecution` + Celery, not the browser): a still-running solve is
 * re-attached, a finished one becomes the "last run". This is what makes a solve
 * survive navigation, a full reload, a duplicated tab, a new device, or power
 * loss — every client independently re-derives the same state from the server.
 */
export function useSolveSession(store: ModelProjectStore, workspaceId?: string): void {
  const taskId = useStore(store, (s) => s.solveSession.taskId);
  const status = useStore(store, (s) => s.solveSession.status);
  const isRunning = status === "running" && !!taskId;

  // Server reconcile WHILE IDLE — not just on mount. Polls the project's latest
  // execution so a solve started in ANOTHER tab / browser / device is picked up
  // and re-attached here (the owner's "open it elsewhere and it knows" case), and
  // also checks immediately when the tab regains focus. Stops as soon as a session
  // becomes active (the `status` dep tears the effect down), handing off to the
  // 1s completion poll + WebSocket below. Best-effort: errors leave the panel idle.
  // (mount-time workspaceId captured in a ref; the endpoint is org-scoped so it's
  // only advisory.)
  const workspaceIdRef = useRef(workspaceId);
  useEffect(() => {
    const modelId = store.getState().modelId;
    if (!modelId || modelId === "new") return;
    if (status !== "idle") return;
    let cancelled = false;
    const check = async () => {
      if (cancelled) return;
      if (typeof document !== "undefined" && document.hidden) return;
      if (store.getState().solveSession.status !== "idle") return;
      try {
        const execs = await api.getProjectExecutions(modelId, { limit: 1 }, workspaceIdRef.current);
        if (!cancelled) applyReconciledExecution(store, execs[0]);
      } catch {
        /* best-effort */
      }
    };
    check();
    const interval = setInterval(check, 7000);
    const onVisible = () => {
      if (typeof document !== "undefined" && !document.hidden) check();
    };
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVisible);
    }
    return () => {
      cancelled = true;
      clearInterval(interval);
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisible);
      }
    };
  }, [store, status]);

  // Live per-incumbent points over the executions WebSocket (SCIP streams; HiGHS/Hexaly don't).
  useExecutionWebSocket(isRunning ? taskId : null, {
    autoReconnect: true,
    onSolveProgress: (event) => {
      const s = store.getState();
      if (s.solveSession.status !== "running") return;
      const point = toProgressPoint(event as SolveProgressEvent, s.solveSession.points.length);
      if (point) s.addSolvePoint(point, event as SolveProgressEvent);
    },
  });

  // Completion via polling — the robust source of truth, independent of the socket.
  useEffect(() => {
    if (!isRunning || !taskId) return;
    let done = false;
    let timer: ReturnType<typeof setInterval> | null = null;
    const stop = () => {
      done = true;
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    };
    const poll = async () => {
      if (done) return;
      try {
        const res = await api.getSolveAsyncStatus(taskId);
        const s = store.getState();
        if (s.solveSession.taskId !== taskId || s.solveSession.status !== "running") {
          stop();
          return;
        }
        if (res.status === "completed") {
          stop();
          const result = unwrapSolveResult(res);
          if (result) {
            const live = s.solveSession.points;
            const points: ProgressPoint[] =
              live.length > 0
                ? live
                : extractProgressHistory(result as unknown as Record<string, unknown>);
            s.finishSolveSession(result, points);
          } else {
            s.failSolveSession("solveFailed");
          }
        } else if (res.status === "failed") {
          stop();
          s.failSolveSession(res.error || "solveFailed");
        }
      } catch {
        // transient poll error — keep trying
      }
    };
    poll();
    timer = setInterval(poll, 1000);
    return () => {
      done = true;
      if (timer) clearInterval(timer);
    };
  }, [taskId, isRunning, store]);
}
