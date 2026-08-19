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
  const projectLoaded = useModelProjectStore((s) => s.projectLoaded);
  const hasDslSource = useModelProjectStore((s) => s.draftDslSource.trim().length > 0);
  const activeDataset = useModelProjectStore((s) => s.activeDataset);
  const stats = useMemo(() => selectModelStats(problem), [problem]);

  // A JModel source that only declares `set I; param w{I}; var x{I}` has no
  // variables until a dataset says what I is. The zero is true, and read next to
  // two scenarios that just solved this model it says "broken" instead. Only
  // once the project has loaded: before that every field is empty for a reason
  // that has nothing to do with the model.
  const ungrounded = projectLoaded && hasDslSource && !activeDataset && stats.varTotal === 0;

  const hasMatrix = stats.varTotal > 0 && stats.constraintTotal > 0;
  // Every count comes from the canonical model, which starts empty and is
  // filled once the project has been read and laid out. Until then this card
  // painted "Class —, Variables 0, Constraints 0": measured at 4 seconds on a
  // 15-variable model, 6 on a 48,556-variable one and 40 on a 22,650-variable
  // one, all of it stating a number that was wrong. A dash says "not known
  // yet", which is the truth for that window.
  const known = (value: string) => (projectLoaded ? value : "—");
  const rows: Array<{ label: string; value: string }> = [
    { label: t("statClass"), value: known(stats.problemClass) },
    { label: t("statVariables"), value: known(String(stats.varTotal)) },
    { label: t("statConstraints"), value: known(String(stats.constraintTotal)) },
    {
      label: t("statDensity"),
      value: hasMatrix && projectLoaded ? `${(stats.density * 100).toFixed(1)}%` : "—",
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
      {ungrounded && (
        <p
          className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200"
          data-testid="stats-ungrounded"
        >
          {t("statsUngrounded")}
        </p>
      )}
    </aside>
  );
}
