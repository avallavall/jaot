"use client";

import { useTranslations } from "next-intl";
import type { IndexedPoint } from "@/components/solve/ParetoChart";

interface TradeOffExplorerProps {
  selectedPoints: readonly IndexedPoint[];
  labels: readonly string[];
}

function formatDelta(a: number, b: number): { abs: string; pct: string | null } {
  const delta = b - a;
  const absStr = delta >= 0 ? `+${delta.toFixed(4)}` : delta.toFixed(4);

  // Percentage is misleading when the baseline is zero or negative:
  //   - zero baseline  -> division by zero / infinite %
  //   - negative baseline -> inverted sign (e.g. -10 -> -8 shows -20% instead of +20%)
  // In those cases we omit the percentage entirely.
  if (a <= 0) {
    return { abs: absStr, pct: null };
  }

  const pct = (delta / a) * 100;
  return {
    abs: absStr,
    pct: pct >= 0 ? `+${pct.toFixed(1)}%` : `${pct.toFixed(1)}%`,
  };
}

export function TradeOffExplorer({ selectedPoints, labels }: TradeOffExplorerProps) {
  const t = useTranslations("solve.charts.pareto");

  if (selectedPoints.length === 0) {
    return (
      <div className="bg-muted/20 border border-dashed border-border rounded-lg p-6 text-center">
        <p className="text-sm text-muted-foreground">{t("selectPointPrompt")}</p>
      </div>
    );
  }

  // Single point selected: show details
  if (selectedPoints.length === 1) {
    const point = selectedPoints[0];
    // Build objective values for all labels (not just f1/f2)
    const objectiveValues: { label: string; value: number }[] = labels.map((label, idx) => {
      if (idx === 0) return { label: label ?? t("objective1"), value: point.f1 };
      if (idx === 1) return { label: label ?? t("objective2"), value: point.f2 };
      // For 3+ objectives, read from objective_values by label, or f<N+1>
      const fromMap = point.objective_values?.[label];
      if (fromMap !== undefined) return { label, value: fromMap };
      const fKey = `f${idx + 1}`;
      const val = (point as unknown as Record<string, unknown>)[fKey];
      return { label, value: typeof val === "number" ? val : 0 };
    });

    return (
      <div className="bg-card border border-border rounded-lg p-5" data-testid="trade-off-single">
        <h4 className="text-sm font-semibold text-foreground mb-3">
          {t("pointNumber", { number: point.index + 1 })} — {t("solutionDetails")}
        </h4>
        <div className="grid grid-cols-2 gap-3 mb-4">
          {objectiveValues.map(({ label, value }) => (
            <div key={label} className="bg-muted/30 rounded-md px-3 py-2">
              <span className="text-xs text-muted-foreground block">{label}</span>
              <span className="font-mono text-sm font-semibold tabular-nums">{value.toFixed(4)}</span>
            </div>
          ))}
        </div>
        <div className="text-xs font-medium text-muted-foreground mb-2">{t("solutionVariables")}</div>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
          {Object.entries(point.solution).map(([name, val]) => (
            <div
              key={name}
              className="flex justify-between gap-2 bg-background border border-border rounded px-2 py-1"
            >
              <span className="font-mono text-xs text-foreground truncate">{name}</span>
              <span className="font-mono text-xs text-muted-foreground tabular-nums flex-shrink-0">
                {val.toFixed(4)}
              </span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // Two points selected: show comparison
  const [pointA, pointB] = selectedPoints;

  // Helper to get objective value for a point by label index
  function getObjVal(point: IndexedPoint, idx: number): number {
    if (idx === 0) return point.f1;
    if (idx === 1) return point.f2;
    const label = labels[idx];
    if (label && point.objective_values?.[label] !== undefined) {
      return point.objective_values[label];
    }
    const fKey = `f${idx + 1}`;
    const val = (point as unknown as Record<string, unknown>)[fKey];
    return typeof val === "number" ? val : 0;
  }

  // Build deltas for all objectives
  const objectiveDeltas = labels.map((label, idx) => ({
    label: label ?? t(idx === 0 ? "objective1" : "objective2"),
    valA: getObjVal(pointA, idx),
    valB: getObjVal(pointB, idx),
    delta: formatDelta(getObjVal(pointA, idx), getObjVal(pointB, idx)),
  }));

  // For the summary string, use first two objectives
  const label1 = objectiveDeltas[0]?.label ?? t("objective1");
  const label2 = objectiveDeltas[1]?.label ?? t("objective2");
  const deltaF1 = objectiveDeltas[0]?.delta ?? formatDelta(0, 0);
  const deltaF2 = objectiveDeltas[1]?.delta ?? formatDelta(0, 0);

  return (
    <div className="bg-card border border-border rounded-lg p-5" data-testid="trade-off-comparison">
      <h4 className="text-sm font-semibold text-foreground mb-3">
        {t("comparisonTitle", { a: pointA.index + 1, b: pointB.index + 1 })}
      </h4>

      <div className="bg-primary/5 border border-primary/20 rounded-md px-4 py-3 mb-4 text-sm">
        {t("tradeOffSummary", {
          obj1: label1,
          delta1: deltaF1.pct ?? deltaF1.abs,
          obj2: label2,
          delta2: deltaF2.pct ?? deltaF2.abs,
        })}
      </div>

      {/* Objective deltas — all objectives */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        {objectiveDeltas.map(({ label, valA, valB, delta }) => (
          <div key={label} className="bg-muted/30 rounded-md px-3 py-2">
            <span className="text-xs text-muted-foreground block mb-1">{label}</span>
            <div className="flex items-baseline gap-2">
              <span className="font-mono text-xs tabular-nums">{valA.toFixed(4)}</span>
              <span className="text-muted-foreground text-xs">{"\u2192"}</span>
              <span className="font-mono text-xs tabular-nums">{valB.toFixed(4)}</span>
              <span className="font-mono text-xs tabular-nums text-primary ml-auto">
                {delta.abs}{delta.pct != null && ` (${delta.pct})`}
              </span>
            </div>
          </div>
        ))}
      </div>

      <div className="text-xs font-medium text-muted-foreground mb-2">{t("variableComparison")}</div>
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
        {Object.keys({ ...pointA.solution, ...pointB.solution }).map((name) => {
          const valA = pointA.solution[name] ?? 0;
          const valB = pointB.solution[name] ?? 0;
          const delta = formatDelta(valA, valB);
          return (
            <div
              key={name}
              className="flex items-center gap-2 bg-background border border-border rounded px-2 py-1.5 text-xs"
            >
              <span className="font-mono text-foreground truncate flex-shrink-0 w-16">{name}</span>
              <span className="font-mono text-muted-foreground tabular-nums">{valA.toFixed(2)}</span>
              <span className="text-muted-foreground">→</span>
              <span className="font-mono text-muted-foreground tabular-nums">{valB.toFixed(2)}</span>
              <span className="font-mono text-primary tabular-nums ml-auto flex-shrink-0">{delta.abs}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
