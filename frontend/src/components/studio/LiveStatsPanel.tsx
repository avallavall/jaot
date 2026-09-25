"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { ModelHealth } from "@/lib/types";
import { useModelProjectStore } from "./store/useModelProjectStore";
import { selectModelStats } from "./store/stats";

/**
 * Persistent right rail — the model "at a glance", live from the canonical store.
 * Health comes from the backend ModelStatsService, like the Analyze tab's card.
 */
export function LiveStatsPanel() {
  const t = useTranslations("studio");
  const problem = useModelProjectStore((s) => s.problem);
  const projectLoaded = useModelProjectStore((s) => s.projectLoaded);
  const hasDslSource = useModelProjectStore((s) => s.draftDslSource.trim().length > 0);
  const activeDataset = useModelProjectStore((s) => s.activeDataset);
  const stats = useMemo(() => selectModelStats(problem), [problem]);
  const modelId = useModelProjectStore((s) => s.modelId);
  const saveState = useModelProjectStore((s) => s.saveState);
  const [health, setHealth] = useState<ModelHealth | null>(null);
  const isPersisted = !!modelId && modelId !== "new";

  // The row said "—" on every model while the Analyze tab beside it showed a
  // grade: nothing ever filled it in. It reads the persisted draft, so it is
  // fetched once the project is loaded and again after each autosave.
  useEffect(() => {
    if (!isPersisted || !projectLoaded || saveState === "saving") return;
    let cancelled = false;
    api
      .getModelStats(modelId)
      .then((s) => {
        if (!cancelled) setHealth(s.health ?? null);
      })
      .catch(() => {
        /* the grade is an extra; the other rows still render */
      });
    return () => {
      cancelled = true;
    };
  }, [modelId, isPersisted, projectLoaded, saveState]);

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
    { label: t("statHealth"), value: health ? `${health.band} · ${health.score}/100` : "—" },
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
