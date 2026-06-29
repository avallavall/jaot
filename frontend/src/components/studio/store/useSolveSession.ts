"use client";

import { useEffect } from "react";
import { useStore } from "zustand";
import { api } from "@/lib/api";
import { useExecutionWebSocket } from "@/hooks/useWebSocket";
import { extractProgressHistory, type ProgressPoint } from "@/lib/result-utils";
import type { AsyncSolveResultEnvelope, SolveResult } from "@/lib/types";
import type { ModelProjectStore } from "./createModelProjectStore";
import { toProgressPoint, type SolveProgressEvent } from "../panels/solve/live-solve-metrics";

/**
 * The completed async-solve status nests the Celery task envelope under `result`,
 * so the actual solver result is `result.result`. Fall back to `result` itself.
 */
function unwrapSolveResult(status: { result?: unknown }): SolveResult | null {
  const envelope = status.result as AsyncSolveResultEnvelope | SolveResult | undefined;
  if (!envelope) return null;
  const inner = (envelope as AsyncSolveResultEnvelope).result;
  return ((inner ?? envelope) as SolveResult) ?? null;
}

/**
 * Drives the async-solve session from the canonical store. Mounted at the
 * PROVIDER / layout level (not in `SolvePanel`) so it keeps polling completion and
 * accumulating live points even while the user is on another tab — the running
 * solve is never lost on a tab switch.
 */
export function useSolveSession(store: ModelProjectStore): void {
  const taskId = useStore(store, (s) => s.solveSession.taskId);
  const status = useStore(store, (s) => s.solveSession.status);
  const isRunning = status === "running" && !!taskId;

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
