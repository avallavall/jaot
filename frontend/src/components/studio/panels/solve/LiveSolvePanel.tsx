"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";
import { useExecutionWebSocket } from "@/hooks/useWebSocket";
import { api } from "@/lib/api";
import { extractProgressHistory, type ProgressPoint } from "@/lib/result-utils";
import type { AsyncSolveResultEnvelope, SolveResult } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { GapConvergenceChart } from "@/components/solve/GapConvergenceChart";
import {
  toProgressPoint,
  computeMetrics,
  type SolveProgressEvent,
} from "./live-solve-metrics";

interface LiveSolvePanelProps {
  /** The async-solve task id (== the WS / Redis channel key the worker publishes to). */
  taskId: string;
  objectiveSense: "minimize" | "maximize";
  onComplete: (result: SolveResult) => void;
  onError: (message: string) => void;
  onCancelled?: () => void;
}

type LiveStatus = "running" | "completed" | "failed" | "cancelled";

/**
 * The completed async-solve status nests the Celery task envelope under `result`,
 * so the actual solver result is `result.result`. Fall back to `result` itself for
 * any non-wrapped shape.
 */
function unwrapSolveResult(status: { result?: unknown }): SolveResult | null {
  const envelope = status.result as AsyncSolveResultEnvelope | SolveResult | undefined;
  if (!envelope) return null;
  const inner = (envelope as AsyncSolveResultEnvelope).result;
  return ((inner ?? envelope) as SolveResult) ?? null;
}

/**
 * Watches a running async solve and renders the live primal/dual convergence chart
 * + metrics. Live points stream over the executions WebSocket (`type:"solve_progress"`);
 * completion is confirmed by polling the async status (the robust source of truth,
 * independent of the socket). If no live points arrived (e.g. the solver doesn't
 * stream — HiGHS/Hexaly — or the socket couldn't connect), the chart falls back to
 * the finished result's `progress_history`.
 *
 * IMPORTANT: the polling effect depends ONLY on `[taskId]`. The completion callbacks
 * are held in refs because `SolvePanel` passes them as inline arrows (new identity
 * each render). If they were effect deps, completion → parent setState → re-render →
 * new callback identities → effect teardown+rerun → `status` reset to "running" →
 * the panel would be stuck on "running" forever even though the solve finished.
 */
export function LiveSolvePanel({
  taskId,
  objectiveSense,
  onComplete,
  onError,
  onCancelled,
}: LiveSolvePanelProps) {
  const t = useTranslations("studio");
  const [points, setPoints] = useState<ProgressPoint[]>([]);
  const [lastEvent, setLastEvent] = useState<SolveProgressEvent | null>(null);
  const [status, setStatus] = useState<LiveStatus>("running");
  const [cancelling, setCancelling] = useState(false);
  const doneRef = useRef(false);

  // Keep the inline callbacks + translator in refs so the polling effect is stable.
  const onCompleteRef = useRef(onComplete);
  const onErrorRef = useRef(onError);
  const tRef = useRef(t);
  useEffect(() => {
    onCompleteRef.current = onComplete;
    onErrorRef.current = onError;
    tRef.current = t;
  });

  // Live points — functional updates keep the callback stable (no stale closure,
  // no socket reconnect churn).
  const handleSolveProgress = useCallback((event: SolveProgressEvent) => {
    if (doneRef.current) return;
    setLastEvent(event);
    setPoints((prev) => {
      const point = toProgressPoint(event, prev.length);
      return point ? [...prev, point] : prev;
    });
  }, []);

  const { isConnected } = useExecutionWebSocket(taskId, {
    autoReconnect: true,
    onSolveProgress: handleSolveProgress,
  });

  // Completion via polling — depends ONLY on taskId (see the component doc above).
  useEffect(() => {
    doneRef.current = false;
    setPoints([]);
    setLastEvent(null);
    setStatus("running");

    let timer: ReturnType<typeof setInterval> | null = null;
    const stop = () => {
      doneRef.current = true;
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    };

    const poll = async () => {
      if (doneRef.current) return;
      try {
        const s = await api.getSolveAsyncStatus(taskId);
        if (s.status === "completed") {
          stop();
          setStatus("completed");
          const solveResult = unwrapSolveResult(s);
          // Fall back to the result's recorded history if nothing streamed live.
          if (solveResult) {
            const history = extractProgressHistory(
              solveResult as unknown as Record<string, unknown>,
            );
            setPoints((prev) => (prev.length > 0 ? prev : history));
            onCompleteRef.current(solveResult);
          } else {
            onErrorRef.current(tRef.current("solveFailed"));
          }
        } else if (s.status === "failed") {
          stop();
          setStatus("failed");
          onErrorRef.current(s.error || tRef.current("solveFailed"));
        }
      } catch {
        // Transient poll error — keep trying.
      }
    };

    poll();
    timer = setInterval(poll, 1000);
    return () => {
      doneRef.current = true;
      if (timer) clearInterval(timer);
    };
  }, [taskId]);

  const handleCancel = useCallback(async () => {
    if (cancelling || doneRef.current) return;
    setCancelling(true);
    try {
      await api.cancelSolveAsync(taskId);
      doneRef.current = true;
      setStatus("cancelled");
      onCancelled?.();
    } catch {
      // Best-effort; if cancel fails the poll will still resolve the run.
    } finally {
      setCancelling(false);
    }
  }, [taskId, cancelling, onCancelled]);

  const metrics = computeMetrics(points, lastEvent);
  const fmt = (v: number | null, digits = 4): string =>
    v === null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: digits });

  return (
    <div className="space-y-4 rounded-lg border border-border p-4">
      <div className="flex items-center gap-2">
        {status === "running" && (
          <Loader2 className="size-4 animate-spin text-primary" aria-hidden="true" />
        )}
        {status === "completed" && (
          <CheckCircle2 className="size-4 text-green-600" aria-hidden="true" />
        )}
        {(status === "failed" || status === "cancelled") && (
          <XCircle className="size-4 text-destructive" aria-hidden="true" />
        )}
        <span className="text-sm font-medium">
          {status === "running"
            ? t("liveRunning")
            : status === "completed"
              ? t("liveDone")
              : status === "cancelled"
                ? t("liveCancelled")
                : t("liveFailed")}
        </span>
        {status === "running" && (
          <span
            className={`ml-auto size-2 rounded-full ${isConnected ? "bg-green-500" : "bg-muted-foreground/40"}`}
            title={isConnected ? t("liveConnected") : t("liveConnecting")}
            aria-hidden="true"
          />
        )}
      </div>

      {points.length === 0 && status === "running" ? (
        <p className="py-6 text-center text-sm text-muted-foreground">{t("liveWaiting")}</p>
      ) : (
        <>
          <div>
            <h4 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {t("liveConvergence")}
            </h4>
            <GapConvergenceChart progressHistory={points} objectiveSense={objectiveSense} />
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            <Metric label={t("liveBestObjective")} value={fmt(metrics.bestObjective, 6)} />
            <Metric
              label={t("liveGap")}
              value={metrics.gap === null ? "—" : `${(metrics.gap * 100).toFixed(2)}%`}
            />
            <Metric label={t("liveNodes")} value={fmt(metrics.nodes, 0)} />
            <Metric label={t("liveIncumbents")} value={String(metrics.incumbents)} />
            <Metric
              label={t("liveElapsed")}
              value={metrics.elapsedSeconds === null ? "—" : `${metrics.elapsedSeconds.toFixed(1)}s`}
            />
          </div>
        </>
      )}

      <p className="text-xs text-muted-foreground">{t("liveStreamNote")}</p>

      {status === "running" && (
        <Button variant="outline" size="sm" onClick={handleCancel} disabled={cancelling}>
          {cancelling ? t("liveCancelling") : t("liveCancel")}
        </Button>
      )}
    </div>
  );
}

interface MetricProps {
  label: string;
  value: string;
}

function Metric({ label, value }: MetricProps) {
  return (
    <div className="rounded-md bg-muted/30 p-2 text-center">
      <div className="font-mono text-sm font-semibold text-foreground">{value}</div>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
    </div>
  );
}
