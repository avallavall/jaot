"use client";

import { useTranslations } from "next-intl";
import { Sparkles } from "lucide-react";
import { useBuilderStore } from "@/hooks/useBuilderStore";
import { Button } from "@/components/ui/button";

/**
 * The Analyze lens — the model's overview as an artifact (structure, health,
 * I/O, "Explain model"). P0 shows live counts; the full ModelStatsService panel,
 * model I/O and the LLM explainer land in later slices.
 */
export function AnalyzePanel() {
  const t = useTranslations("studio");
  const nodes = useBuilderStore((s) => s.nodes);

  const variables = nodes.filter((n) => n.type === "variable").length;
  const constraints = nodes.filter((n) => n.type === "constraint").length;

  const stats: Array<{ label: string; value: string }> = [
    { label: t("statClass"), value: "—" },
    { label: t("statVariables"), value: String(variables) },
    { label: t("statConstraints"), value: String(constraints) },
    { label: t("statDensity"), value: "—" },
    { label: t("statHealth"), value: "—" },
  ];

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <h2 className="text-lg font-semibold">{t("analyzeTitle")}</h2>
            <p className="text-sm text-muted-foreground">
              {t("analyzeSubtitle")}
            </p>
          </div>
          <Button variant="outline" size="sm" disabled>
            <Sparkles className="h-4 w-4 mr-1" />
            {t("explainModel")}
          </Button>
        </div>

        <dl className="grid grid-cols-2 sm:grid-cols-3 gap-4">
          {stats.map((stat) => (
            <div key={stat.label} className="rounded-lg border p-4">
              <dt className="text-xs uppercase tracking-wider text-muted-foreground">
                {stat.label}
              </dt>
              <dd className="text-2xl font-semibold tabular-nums mt-1">
                {stat.value}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
