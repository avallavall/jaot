"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { ModelStats } from "@/lib/types";
import { useModelProjectStore } from "../store/useModelProjectStore";
import { selectModelStats } from "../store/stats";

const HEALTH_TONE: Record<string, string> = {
  A: "text-emerald-600",
  B: "text-emerald-600",
  C: "text-amber-600",
  D: "text-amber-600",
  F: "text-destructive",
};

/**
 * The Analyze lens — the model's overview as an artifact. Two layers: instant
 * client-side structure stats from the canonical store (zero latency, recomputed
 * on every edit) and the authoritative backend `ModelStatsService` (problem class,
 * health score, warnings), fetched after the draft settles. The LLM "Explain model"
 * button is a stub until the studio AI tab provides a project conversation.
 */
export function AnalyzePanel() {
  const t = useTranslations("studio");
  const problem = useModelProjectStore((s) => s.problem);
  const modelId = useModelProjectStore((s) => s.modelId);
  const saveState = useModelProjectStore((s) => s.saveState);
  const stats = useMemo(() => selectModelStats(problem), [problem]);
  const [backend, setBackend] = useState<ModelStats | null>(null);

  const isPersisted = !!modelId && modelId !== "new";

  // Authoritative backend stats reflect the persisted draft, so refetch on mount
  // and after each successful autosave ("saved").
  useEffect(() => {
    if (!isPersisted) return;
    if (saveState === "saving") return;
    let cancelled = false;
    api
      .getModelStats(modelId)
      .then((s) => {
        if (!cancelled) setBackend(s);
      })
      .catch(() => {
        /* backend stats are an enhancement — the client stats still render */
      });
    return () => {
      cancelled = true;
    };
  }, [modelId, isPersisted, saveState]);

  const hasMatrix = stats.varTotal > 0 && stats.constraintTotal > 0;
  const problemClass = backend?.problem_class ?? stats.problemClass;
  const cards: Array<{ label: string; value: string }> = [
    { label: t("statClass"), value: problemClass },
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
          <Button variant="outline" size="sm" disabled title={t("comingSoon")}>
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

        {backend && (
          <div className="mt-6 rounded-lg border p-4">
            <div className="flex items-center justify-between">
              <div>
                <dt className="text-xs uppercase tracking-wider text-muted-foreground">
                  {t("statHealth")}
                </dt>
                <dd className="mt-1 flex items-baseline gap-2">
                  <span
                    className={`text-2xl font-semibold tabular-nums ${HEALTH_TONE[backend.health.band] ?? ""}`}
                  >
                    {backend.health.band}
                  </span>
                  <span className="text-sm text-muted-foreground tabular-nums">
                    {backend.health.score}/100
                  </span>
                </dd>
              </div>
            </div>
            {backend.warnings.length > 0 && (
              <ul className="mt-3 space-y-1 text-xs text-muted-foreground list-disc list-inside">
                {backend.warnings.slice(0, 6).map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
