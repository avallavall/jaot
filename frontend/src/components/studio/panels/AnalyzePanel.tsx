"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useModelProjectStore } from "../store/useModelProjectStore";
import { selectModelStats } from "../store/stats";

/**
 * The Analyze lens — the model's overview as an artifact (structure, health, I/O,
 * "Explain model"). P0/2A shows live structure stats from the canonical store; the
 * backend ModelStatsService (health score, sparsity), model I/O and the LLM
 * explainer land in later slices.
 */
export function AnalyzePanel() {
  const t = useTranslations("studio");
  const problem = useModelProjectStore((s) => s.problem);
  const stats = useMemo(() => selectModelStats(problem), [problem]);

  const hasMatrix = stats.varTotal > 0 && stats.constraintTotal > 0;
  const cards: Array<{ label: string; value: string }> = [
    { label: t("statClass"), value: stats.problemClass },
    { label: t("statVariables"), value: String(stats.varTotal) },
    { label: t("statConstraints"), value: String(stats.constraintTotal) },
    {
      label: t("statComposition"),
      value: `${stats.varBinary} · ${stats.varInteger} · ${stats.varContinuous}`,
    },
    { label: t("statNonzeros"), value: String(stats.nonzeros) },
    {
      label: t("statDensity"),
      value: hasMatrix ? `${(stats.density * 100).toFixed(1)}%` : "—",
    },
  ];

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <h2 className="text-lg font-semibold">{t("analyzeTitle")}</h2>
            <p className="text-sm text-muted-foreground">{t("analyzeSubtitle")}</p>
          </div>
          <Button variant="outline" size="sm" disabled>
            <Sparkles className="h-4 w-4 mr-1" />
            {t("explainModel")}
          </Button>
        </div>

        <dl className="grid grid-cols-2 sm:grid-cols-3 gap-4">
          {cards.map((card) => (
            <div key={card.label} className="rounded-lg border p-4">
              <dt className="text-xs uppercase tracking-wider text-muted-foreground">
                {card.label}
              </dt>
              <dd className="text-2xl font-semibold tabular-nums mt-1">{card.value}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
