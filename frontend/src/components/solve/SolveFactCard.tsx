"use client";

import { useTranslations } from "next-intl";

interface SolveFactCardProps {
  /** The persisted `solver_status` (optimal | feasible | time_limit | ...). */
  status?: string | null;
  objectiveValue?: number | null;
  gap?: number | null;
  nodes?: number | null;
  iterations?: number | null;
  solveTimeSeconds?: number | null;
}

/**
 * Honest post-solve summary (A2). Replaces the live convergence chart, which was
 * empirically useless for real models: SCIP finds the incumbent almost
 * immediately then spends the run proving optimality, so the per-incumbent
 * stream is ~2 points — a flat line even when the model branched 1936 nodes. A
 * fact-card ("proven at the root node" / "optimal after N nodes" / "time limit —
 * gap X%") is both truthful and more persuasive of solver quality than a fake
 * curve. A real dual-bound-vs-time chart is deferred until the backend streams
 * the dual bound (not just incumbents).
 */
export function SolveFactCard({
  status,
  objectiveValue,
  gap,
  nodes,
  iterations,
  solveTimeSeconds,
}: SolveFactCardProps) {
  const t = useTranslations("solve.execution.summary");
  const gapPct = gap != null ? `${(gap * 100).toFixed(2)}%` : "—";

  const { key, values } = headline(status, nodes, gap);

  const fmtNum = (v: number | null | undefined, digits = 6): string =>
    v == null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: digits });

  return (
    <div
      data-testid="solve-fact-card"
      className="bg-card border border-border rounded-lg p-4 space-y-3"
    >
      <p className="text-sm font-medium text-foreground">{t(key, values)}</p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        <Metric label={t("objective")} value={fmtNum(objectiveValue)} />
        <Metric label={t("gap")} value={gapPct} />
        <Metric label={t("nodes")} value={nodes != null ? fmtNum(nodes, 0) : "—"} />
        <Metric label={t("iterations")} value={iterations != null ? fmtNum(iterations, 0) : "—"} />
        <Metric
          label={t("time")}
          value={solveTimeSeconds != null ? `${solveTimeSeconds.toFixed(2)}s` : "—"}
        />
      </div>
    </div>
  );
}

/** Pick the honest headline. `nodes` drives the optimal case: absent (old rows /
 *  solvers that don't report it) degrades to the plain "optimal proven". */
function headline(
  status: string | null | undefined,
  nodes: number | null | undefined,
  gap: number | null | undefined,
): { key: string; values: Record<string, string | number> } {
  const gapPct = gap != null ? `${(gap * 100).toFixed(2)}%` : "—";
  switch (status) {
    case "time_limit":
      return { key: "headlineTimeLimit", values: { gap: gapPct } };
    case "infeasible":
      return { key: "headlineInfeasible", values: {} };
    case "unbounded":
      return { key: "headlineUnbounded", values: {} };
    case "feasible":
      return { key: "headlineFeasible", values: { gap: gapPct } };
    case "optimal":
      if (nodes != null && nodes <= 1) return { key: "headlineRootNode", values: {} };
      if (nodes != null && nodes > 1) return { key: "headlineBranched", values: { nodes } };
      return { key: "headlineOptimal", values: {} };
    default:
      return { key: "headlineSolved", values: {} };
  }
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-muted/30 p-2 text-center">
      <div className="font-mono text-sm font-semibold text-foreground tabular-nums">{value}</div>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
    </div>
  );
}
