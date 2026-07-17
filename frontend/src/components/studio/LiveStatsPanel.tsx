"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { useModelProjectStore } from "./store/useModelProjectStore";
import { selectModelStats } from "./store/stats";

/**
 * Persistent right rail — the model "at a glance", live from the canonical store.
 * Health is wired to the backend ModelStatsService (health score) in P1.
 */
export function LiveStatsPanel() {
  const t = useTranslations("studio");
  const problem = useModelProjectStore((s) => s.problem);
  const stats = useMemo(() => selectModelStats(problem), [problem]);

  const hasMatrix = stats.varTotal > 0 && stats.constraintTotal > 0;
  const rows: Array<{ label: string; value: string }> = [
    { label: t("statClass"), value: stats.problemClass },
    { label: t("statVariables"), value: String(stats.varTotal) },
    { label: t("statConstraints"), value: String(stats.constraintTotal) },
    {
      label: t("statDensity"),
      value: hasMatrix ? `${(stats.density * 100).toFixed(1)}%` : "—",
    },
    { label: t("statHealth"), value: "—" },
  ];

  return (
    <aside
      aria-label={t("statsTitle")}
      className="hidden lg:flex w-64 shrink-0 flex-col border-l p-4 overflow-y-auto"
    >
      <h2 className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-3">
        {t("statsTitle")}
      </h2>
      <dl className="space-y-2">
        {rows.map((row) => (
          <div key={row.label} className="flex items-center justify-between text-sm">
            <dt className="text-muted-foreground">{row.label}</dt>
            <dd className="font-medium tabular-nums">{row.value}</dd>
          </div>
        ))}
      </dl>
    </aside>
  );
}
