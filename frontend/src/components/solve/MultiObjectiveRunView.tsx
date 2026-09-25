"use client";

import { useTranslations } from "next-intl";

import { ParetoChart } from "@/components/solve/ParetoChart";
import type { MultiObjectiveResult } from "@/lib/types";

interface MultiObjectiveRunViewProps {
  front: MultiObjectiveResult;
}

/**
 * A saved multi-objective run: what kind of run it was, and its front.
 *
 * The chart below lists every point with the value of each objective, so the
 * page shows the same trade-offs the multi-objective page showed when the run
 * finished.
 */
export function MultiObjectiveRunView({ front }: MultiObjectiveRunViewProps) {
  const t = useTranslations("solve.execution.multiObjective");
  const mode = front.mode === "weighted" ? t("modeWeighted") : t("modeEpsilon");

  return (
    <div className="mb-8" data-testid="multi-objective-run">
      <h2 className="text-lg font-semibold text-foreground mb-1">{t("title")}</h2>
      <p className="text-sm text-muted-foreground mb-4" data-testid="multi-objective-summary">
        {t("summary", { count: front.n_solved, mode })}
      </p>
      {front.pareto_points.length > 0 ? (
        <div className="bg-card border border-border rounded-lg p-4">
          <ParetoChart result={front} />
        </div>
      ) : (
        <p className="text-sm text-muted-foreground" data-testid="multi-objective-empty">
          {t("empty")}
        </p>
      )}
    </div>
  );
}
