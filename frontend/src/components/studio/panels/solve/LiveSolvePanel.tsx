"use client";

import { useTranslations } from "next-intl";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { GapConvergenceChart } from "@/components/solve/GapConvergenceChart";
import type { SolveSession } from "../../store/createModelProjectStore";
import { computeMetrics } from "./live-solve-metrics";

interface LiveSolvePanelProps {
  /** The current solve session (from the canonical store — survives tab switches). */
  session: SolveSession;
  objectiveSense: "minimize" | "maximize";
  onCancel?: () => void;
}

/**
 * Presentational view of a solve session. It owns NO polling/WS/state — those run in
 * `useSolveSession` at the provider level so the run survives tab switches; this panel
 * just renders the store's `solveSession`. Shows the live primal/dual convergence chart
 * when per-incumbent points streamed (SCIP); for solvers that don't stream (HiGHS,
 * Hexaly) it shows a clean final-result summary instead of an empty live box.
 */
export function LiveSolvePanel({ session, objectiveSense, onCancel }: LiveSolvePanelProps) {
  const t = useTranslations("studio");
  const { status, points, lastEvent, result, solverName } = session;
  const metrics = computeMetrics(points, lastEvent);
  const fmt = (v: number | null, digits = 4): string =>
    v === null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: digits });

  const running = status === "running";
  const done = status === "done";
  const hasPoints = points.length > 0;

  return (
    <div className="space-y-4 rounded-lg border border-border p-4">
      <div className="flex items-center gap-2">
        {running && <Loader2 className="size-4 animate-spin text-primary" aria-hidden="true" />}
        {done && <CheckCircle2 className="size-4 text-green-600" aria-hidden="true" />}
        {(status === "failed" || status === "cancelled") && (
          <XCircle className="size-4 text-destructive" aria-hidden="true" />
        )}
        <span className="text-sm font-medium">
          {running
            ? t("liveRunning")
            : done
              ? t("liveDone")
              : status === "cancelled"
                ? t("liveCancelled")
                : t("liveFailed")}
        </span>
      </div>

      {running && !hasPoints && (
        <p className="py-6 text-center text-sm text-muted-foreground">{t("liveWaiting")}</p>
      )}

      {hasPoints && (
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

      {/* Solved, but the solver didn't stream per-incumbent (HiGHS/Hexaly): final summary. */}
      {done && !hasPoints && result && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Metric
              label={t("liveBestObjective")}
              value={
                result.objective_value != null
                  ? result.objective_value.toLocaleString(undefined, { maximumFractionDigits: 6 })
                  : "—"
              }
            />
            <Metric label={t("solveStatusLabel")} value={result.status ?? "—"} />
            <Metric
              label={t("solveSolverLabel")}
              value={result.solver_used ?? solverName ?? "—"}
            />
            <Metric
              label={t("liveElapsed")}
              value={
                result.solve_time_seconds != null
                  ? `${result.solve_time_seconds.toFixed(2)}s`
                  : "—"
              }
            />
          </div>
        </div>
      )}

      <p className="text-xs text-muted-foreground">{t("liveStreamNote")}</p>

      {running && onCancel && (
        <Button variant="outline" size="sm" onClick={onCancel}>
          {t("liveCancel")}
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
