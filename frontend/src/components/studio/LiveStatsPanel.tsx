"use client";

import { useTranslations } from "next-intl";
import { useBuilderStore } from "@/hooks/useBuilderStore";

/**
 * Persistent right rail — the model "at a glance". P0 shows live variable and
 * constraint counts from the shared store; class/density/health are wired to the
 * backend ModelStatsService in a later slice (placeholders for now).
 */
export function LiveStatsPanel() {
  const t = useTranslations("studio");
  const nodes = useBuilderStore((s) => s.nodes);

  const variables = nodes.filter((n) => n.type === "variable").length;
  const constraints = nodes.filter((n) => n.type === "constraint").length;

  const rows: Array<{ label: string; value: string }> = [
    { label: t("statClass"), value: "—" },
    { label: t("statVariables"), value: String(variables) },
    { label: t("statConstraints"), value: String(constraints) },
    { label: t("statDensity"), value: "—" },
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
          <div
            key={row.label}
            className="flex items-center justify-between text-sm"
          >
            <dt className="text-muted-foreground">{row.label}</dt>
            <dd className="font-medium tabular-nums">{row.value}</dd>
          </div>
        ))}
      </dl>
    </aside>
  );
}
