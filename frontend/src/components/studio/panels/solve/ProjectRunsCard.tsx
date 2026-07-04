"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations, useFormatter, useNow } from "next-intl";
import { History } from "lucide-react";
import { Link, useRouter } from "@/i18n/navigation";
import { api } from "@/lib/api";
import type { ProjectExecutionItem } from "@/lib/types";
import { useModelProjectStore } from "../../store/useModelProjectStore";

const POLL_MS = 7000;
const LIMIT = 15;

const STATUS_TONE: Record<string, string> = {
  completed: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300",
  failed: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  running: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
  pending: "bg-yellow-100 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-300",
};

/**
 * Per-project run history on the Solve tab (owner ask 2026-07-04): the global
 * history under Solve → Executions shows EVERYTHING; this card lists only THIS
 * model's runs (server truth via `GET /projects/{id}/executions`, the §14
 * endpoint), newest first, with the dataset each run was compiled against (S1).
 * Rows link to the execution detail; polls lightly while any run is live.
 */
export function ProjectRunsCard() {
  const t = useTranslations("studio");
  const format = useFormatter();
  const now = useNow({ updateInterval: 60_000 });
  const router = useRouter();
  const modelId = useModelProjectStore((s) => s.modelId);
  const isPersisted = !!modelId && modelId !== "new";

  const [runs, setRuns] = useState<ProjectExecutionItem[]>([]);

  const refresh = useCallback(() => {
    if (!isPersisted) return;
    api
      .getProjectExecutions(modelId, { limit: LIMIT })
      .then(setRuns)
      .catch(() => {
        /* transient — keep previous rows */
      });
  }, [modelId, isPersisted]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const hasLive = useMemo(
    () => runs.some((r) => r.status === "pending" || r.status === "running"),
    [runs],
  );

  useEffect(() => {
    if (!hasLive) return;
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [hasLive, refresh]);

  if (!isPersisted || runs.length === 0) return null;

  const fmt = (v: number | null | undefined) =>
    v == null ? "—" : Number.isInteger(v) ? String(v) : v.toFixed(4);

  return (
    <section
      data-testid="studio-project-runs"
      className="mx-auto mt-8 w-full max-w-3xl rounded-lg border p-4"
    >
      <div className="flex items-center justify-between gap-3">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold">
          <History className="h-4 w-4 text-muted-foreground" />
          {t("projectRunsTitle")}
        </h3>
        <Link
          href="/solve/executions"
          className="shrink-0 text-xs text-primary hover:underline"
          data-testid="studio-project-runs-global"
        >
          {t("projectRunsOpenGlobal")}
        </Link>
      </div>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-xs uppercase tracking-wider text-muted-foreground">
              <th className="py-2 pr-3 font-medium">{t("projectRunsColWhen")}</th>
              <th className="py-2 pr-3 font-medium">{t("scenariosColStatus")}</th>
              <th className="py-2 pr-3 font-medium">{t("scenariosColDataset")}</th>
              <th className="py-2 pr-3 text-right font-medium">{t("scenariosColObjective")}</th>
              <th className="py-2 pr-3 text-right font-medium">{t("scenariosColTime")}</th>
              <th className="py-2 font-medium">{t("scenariosColSolver")}</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr
                key={run.id}
                className="cursor-pointer border-b last:border-0 hover:bg-muted/40"
                onClick={() => router.push(`/solve/executions/${run.id}`)}
                data-testid="studio-project-run-row"
              >
                <td className="py-2 pr-3 whitespace-nowrap text-muted-foreground">
                  {format.relativeTime(new Date(run.created_at), now)}
                </td>
                <td className="py-2 pr-3">
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs ${STATUS_TONE[run.status] ?? "bg-muted text-muted-foreground"}`}
                    title={run.error_message ?? undefined}
                  >
                    {run.status}
                  </span>
                </td>
                <td className="max-w-[12rem] truncate py-2 pr-3 text-muted-foreground">
                  {run.dataset_name ?? "—"}
                </td>
                <td className="py-2 pr-3 text-right font-mono tabular-nums">
                  {fmt(run.objective_value)}
                </td>
                <td className="py-2 pr-3 text-right text-muted-foreground tabular-nums">
                  {run.execution_time_ms != null ? `${run.execution_time_ms}ms` : "—"}
                </td>
                <td className="py-2 text-muted-foreground">
                  {run.solver_name?.toUpperCase() ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
