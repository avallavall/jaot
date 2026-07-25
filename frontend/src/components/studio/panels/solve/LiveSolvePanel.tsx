"use client";

import { useTranslations } from "next-intl";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { solverDisplayName } from "@/lib/solver-display";
import type { SolverCapabilities } from "@/lib/types";
import type { SolveSession } from "../../store/createModelProjectStore";
import { computeMetrics } from "./live-solve-metrics";

interface LiveSolvePanelProps {
  /** The current solve session (from the canonical store — survives tab switches). */
  session: SolveSession;
  onCancel?: () => void;
  /** What the session's solver can deliver. Undefined = unknown, so claim nothing. */
  capabilities?: SolverCapabilities;
}

/**
 * Presentational view of a solve session. It owns NO polling/WS/state — those run in
 * `useSolveSession` at the provider level so the run survives tab switches; this panel
 * just renders the store's `solveSession`. Shows the live primal/dual convergence chart
 * when per-incumbent points streamed (SCIP); for solvers that don't stream (HiGHS,
 * Hexaly) it shows a clean final-result summary instead of an empty live box.
 */
export function LiveSolvePanel({ session, onCancel, capabilities }: LiveSolvePanelProps) {
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

      {/* "Waiting for the first solution" is only true for a solver that will
          eventually send one. HiGHS exposes no per-incumbent callback and Hexaly
          is a metaheuristic with none wired, so on those this box used to sit on
          "waiting" for the whole solve and then jump straight to the result.
          When the solver declares it does not stream, say so instead (v3.2). */}
      {running && !hasPoints && (
        <p className="py-6 text-center text-sm text-muted-foreground">
          {capabilities?.progress === false && solverName
            ? t("liveNoProgressStream", { solver: solverDisplayName(solverName) })
            : t("liveWaiting")}
        </p>
      )}

      {/* Live metrics as they stream (SCIP). The convergence CHART was removed
          (A2): the per-incumbent stream is ~2 points — a flat line even when the
          model branches thousands of nodes — so the honest numbers below carry
          the signal, not a fake curve. */}
      {hasPoints && (
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
      )}

      {/* Solved, but the solver didn't stream per-incumbent (HiGHS/Hexaly): final summary. */}
      {done && !hasPoints && result && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Metric
              label={t("liveBestObjective")}
              testid="studio-solve-objective"
              value={
                result.objective_value != null
                  ? result.objective_value.toLocaleString(undefined, { maximumFractionDigits: 6 })
                  : "—"
              }
            />
            <Metric label={t("solveStatusLabel")} value={result.status ?? "—"} />
            <Metric
              label={t("solveSolverLabel")}
              /* Same brand casing as the note below it — the panel used to show
                 "highs" here and "HiGHS" there, in the same box. */
              value={solverDisplayName(result.solver_used ?? solverName ?? "") || "—"}
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

      {/* Which solver actually ran (resolves "Auto" -> the chosen solver) + any
          auto-route reason / fallback warning. Shown once solved. */}
      {done && result && (result.solver_used || result.auto_route_reason || result.warning) && (
        <div className="rounded-md bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
          <span>
            {t("solveSolverLabel")}:{" "}
            <span className="font-medium text-foreground">
              {solverDisplayName(result.solver_used ?? solverName ?? "") || "—"}
            </span>
          </span>
          {result.auto_route_reason && (
            <span className="ml-2 rounded bg-muted px-1.5 py-0.5">{t("autoRouted")}</span>
          )}
          {result.warning && <div className="mt-1 text-amber-600">{result.warning}</div>}
        </div>
      )}

      {/* The generic "some solvers stream, others don't" note is only worth
          showing while we cannot name THIS solver's behaviour — under "auto",
          or when the listing did not tell us. Once capabilities are known the
          concrete message above says it better, and the generic copy hard-codes
          solver names that would quietly become wrong if an adapter gains a
          progress callback. */}
      {capabilities === undefined && (
        <p className="text-xs text-muted-foreground">{t("liveStreamNote")}</p>
      )}

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
  testid?: string;
}

function Metric({ label, value, testid }: MetricProps) {
  return (
    <div className="rounded-md bg-muted/30 p-2 text-center">
      <div data-testid={testid} className="font-mono text-sm font-semibold text-foreground">
        {value}
      </div>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
    </div>
  );
}
