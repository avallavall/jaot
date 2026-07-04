"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { FlaskConical, GitCompareArrows, Play } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";
import type { ProjectExecutionItem } from "@/lib/types";
import { useAuth } from "@/contexts/AuthContext";
import { useDslStatus } from "@/hooks/useDslStatus";
import { useModelProjectStore } from "../../store/useModelProjectStore";
import { useProjectDatasets } from "../../datasets/useProjectDatasets";

const POLL_MS = 5000;
const DIFF_ROW_CAP = 50;
// Launching is CLIENT-side work (compile -> download compiled problem -> upload to
// /solve/async — up to ~31MB each way for the big TFM scenarios). Firing 16 at once
// queued them behind the browser's ~6-connection limit for minutes; capping the
// batch keeps each launch's vulnerable window short (live report 2026-07-04).
const CONCURRENT_LAUNCHES = 3;

interface DiffRow {
  name: string;
  a: number | null;
  b: number | null;
}

interface DiffState {
  aName: string;
  bName: string;
  rows: DiffRow[];
  hiddenCount: number;
}

const STATUS_TONE: Record<string, string> = {
  completed: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300",
  failed: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  running: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
  pending: "bg-yellow-100 text-yellow-800 dark:bg-yellow-950 dark:text-yellow-300",
};

function variableMap(result: unknown): Map<string, number> {
  const map = new Map<string, number>();
  const variables = (result as { variables?: Array<{ name?: string; value?: number }> } | null)
    ?.variables;
  if (Array.isArray(variables)) {
    for (const v of variables) {
      if (typeof v?.name === "string" && typeof v?.value === "number") map.set(v.name, v.value);
    }
  }
  return map;
}

/**
 * The Solve tab's "Scenarios" section (S3): run the project's JModel against N
 * selected datasets in one click and compare the outcomes side by side.
 *
 * Each dataset compiles client-side (`/dsl/compile?dataset_id`) — a dataset that
 * does not fill the model becomes a failed ROW with the structured compiler
 * message, never a crash — and solves through the universal async path tagged
 * with `dataset_id` (S1). The comparison table is SERVER-DERIVED (latest
 * execution per dataset from `GET /projects/{id}/executions`), so it is durable
 * across tabs/devices/reloads by construction, refreshed while any run is live.
 */
export function ScenariosSection({ solverName }: { solverName: string }) {
  const t = useTranslations("studio");
  const dslEnabled = useDslStatus();
  const modelId = useModelProjectStore((s) => s.modelId);
  const draftDslSource = useModelProjectStore((s) => s.draftDslSource);
  const { activeWorkspaceId } = useAuth();
  const isPersisted = !!modelId && modelId !== "new";
  const { datasets } = useProjectDatasets(isPersisted ? modelId : null);

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [launching, setLaunching] = useState(false);
  // Per-dataset transient launch phase. Large scenarios spend 10-30s in
  // compile+upload before a ModelExecution row exists server-side; without this
  // the table showed NOTHING while the browser worked (live report 2026-07-04).
  const [launchPhases, setLaunchPhases] = useState<Record<string, "compiling" | "queueing">>({});
  const [compileFailures, setCompileFailures] = useState<Record<string, string>>({});
  const [runs, setRuns] = useState<ProjectExecutionItem[]>([]);
  const [diff, setDiff] = useState<DiffState | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);

  const refreshRuns = useCallback(async () => {
    if (!isPersisted) return;
    try {
      setRuns(await api.getProjectExecutions(modelId, { limit: 100 }));
    } catch {
      /* transient — keep the previous rows */
    }
  }, [modelId, isPersisted]);

  useEffect(() => {
    void refreshRuns();
  }, [refreshRuns]);

  // Latest execution per dataset (rows arrive newest-first from the server).
  const latestByDataset = useMemo(() => {
    const map = new Map<string, ProjectExecutionItem>();
    for (const run of runs) {
      if (run.dataset_id && !map.has(run.dataset_id)) map.set(run.dataset_id, run);
    }
    return map;
  }, [runs]);

  const hasLive = useMemo(
    () =>
      [...latestByDataset.values()].some((r) => r.status === "pending" || r.status === "running"),
    [latestByDataset],
  );

  // Light poll while any scenario run is still live (the table is server truth).
  useEffect(() => {
    if (!hasLive) return;
    const id = setInterval(() => void refreshRuns(), POLL_MS);
    return () => clearInterval(id);
  }, [hasLive, refreshRuns]);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    setDiff(null);
  };

  const handleRunAll = async () => {
    if (launching || selected.size === 0 || !draftDslSource.trim()) return;
    setLaunching(true);
    setDiff(null);
    const failures: Record<string, string> = {};
    setLaunchPhases(Object.fromEntries([...selected].map((id) => [id, "compiling"] as const)));
    const launchOne = async (dsId: string) => {
        try {
          const compiled = await api.compileDsl(draftDslSource, dsId);
          if (!compiled.ok || !compiled.problem) {
            failures[dsId] = compiled.error?.message ?? t("scenariosCompileFailed");
            return;
          }
          setLaunchPhases((prev) => ({ ...prev, [dsId]: "queueing" }));
          await api.solveAsync(
            { ...compiled.problem, solver_name: solverName },
            activeWorkspaceId ?? undefined,
            {
              origin: "visual_builder",
              sourceKind: "model_project",
              sourceId: modelId,
              datasetId: dsId,
            },
          );
          // Refresh per launch: this dataset's row flips to pending/running as
          // soon as IT is queued, instead of waiting for every sibling (a big
          // scenario compiling must not hide a small one already solving).
          void refreshRuns();
        } catch (err: unknown) {
          failures[dsId] = getErrorMessage(err, t("scenariosLaunchFailed"));
        } finally {
          setLaunchPhases((prev) => {
            const next = { ...prev };
            delete next[dsId];
            return next;
          });
        }
    };
    const ids = [...selected];
    for (let i = 0; i < ids.length; i += CONCURRENT_LAUNCHES) {
      await Promise.all(ids.slice(i, i + CONCURRENT_LAUNCHES).map(launchOne));
    }
    setCompileFailures(failures);
    await refreshRuns();
    setLaunching(false);
  };

  // A reload/close ABORTS in-flight launches (fetches die client-side): datasets
  // still uploading silently fall back to "no runs" after F5 (live 2026-07-04).
  // Ask the browser to confirm leaving while a batch is launching.
  useEffect(() => {
    if (!launching) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [launching]);

  // Solution diff for EXACTLY two selected datasets with completed latest runs.
  const comparable = useMemo(() => {
    if (selected.size !== 2) return null;
    const pair = [...selected].map((id) => ({
      dataset: datasets.find((d) => d.id === id),
      run: latestByDataset.get(id),
    }));
    if (pair.some((p) => !p.dataset || !p.run || p.run.status !== "completed")) return null;
    return pair as Array<{
      dataset: NonNullable<(typeof pair)[number]["dataset"]>;
      run: ProjectExecutionItem;
    }>;
  }, [selected, datasets, latestByDataset]);

  const handleCompare = async () => {
    if (!comparable || diffLoading) return;
    setDiffLoading(true);
    try {
      const [exA, exB] = await Promise.all(
        comparable.map((p) => api.getExecution(p.run.id)),
      );
      const mapA = variableMap(exA.result_data);
      const mapB = variableMap(exB.result_data);
      const names = [...new Set([...mapA.keys(), ...mapB.keys()])].sort();
      const rows: DiffRow[] = [];
      for (const name of names) {
        const a = mapA.get(name) ?? null;
        const b = mapB.get(name) ?? null;
        const differs = a === null || b === null ? a !== b : Math.abs(a - b) > 1e-9;
        if (differs) rows.push({ name, a, b });
      }
      setDiff({
        aName: comparable[0].dataset.name,
        bName: comparable[1].dataset.name,
        rows: rows.slice(0, DIFF_ROW_CAP),
        hiddenCount: Math.max(0, rows.length - DIFF_ROW_CAP),
      });
    } catch (err: unknown) {
      toast.error(getErrorMessage(err, t("scenariosDiffFailed")));
    } finally {
      setDiffLoading(false);
    }
  };

  if (!dslEnabled || !isPersisted || datasets.length === 0) return null;

  const hasSource = draftDslSource.trim().length > 0;

  const fmt = (v: number | null | undefined) =>
    v == null ? "—" : Number.isInteger(v) ? String(v) : v.toFixed(4);

  return (
    <section
      data-testid="studio-scenarios"
      className="mx-auto mt-8 w-full max-w-3xl rounded-lg border p-4"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold">
            <FlaskConical className="h-4 w-4 text-muted-foreground" />
            {t("scenariosTitle")}
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">{t("scenariosHint")}</p>
        </div>
        <Button
          size="sm"
          onClick={() => void handleRunAll()}
          disabled={launching || selected.size === 0 || !hasSource}
          title={!hasSource ? t("scenariosNeedsJModel") : undefined}
          data-testid="studio-scenarios-run-all"
          className="shrink-0"
        >
          <Play className="mr-1 h-3.5 w-3.5" />
          {t("scenariosRunAll", { count: selected.size })}
        </Button>
      </div>

      {/* A flat/imported model is already grounded — scenarios recompile a JModel
          SOURCE with each dataset. Without one the run-all button would sit mutely
          disabled (live-testing 2026-07-04), so say WHY and point at the lens. */}
      {!hasSource && (
        <p
          className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200"
          data-testid="studio-scenarios-needs-jmodel"
        >
          {t("scenariosNeedsJModel")}{" "}
          <Link
            href={`/studio/${modelId}/build?lens=jmodel`}
            className="font-medium underline underline-offset-2"
            data-testid="studio-scenarios-open-jmodel"
          >
            {t("scenariosOpenJModel")}
          </Link>
        </p>
      )}

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-xs uppercase tracking-wider text-muted-foreground">
              <th className="py-2 pr-2 font-medium"></th>
              <th className="py-2 pr-3 font-medium">{t("scenariosColDataset")}</th>
              <th className="py-2 pr-3 font-medium">{t("scenariosColStatus")}</th>
              <th className="py-2 pr-3 text-right font-medium">{t("scenariosColObjective")}</th>
              <th className="py-2 pr-3 text-right font-medium">{t("scenariosColTime")}</th>
              <th className="py-2 font-medium">{t("scenariosColSolver")}</th>
            </tr>
          </thead>
          <tbody>
            {datasets.map((ds) => {
              const run = latestByDataset.get(ds.id);
              const failure = compileFailures[ds.id];
              return (
                <tr key={ds.id} className="border-b last:border-0" data-testid="studio-scenario-row">
                  <td className="py-2 pr-2">
                    <input
                      type="checkbox"
                      checked={selected.has(ds.id)}
                      onChange={() => toggle(ds.id)}
                      aria-label={t("scenariosSelect", { name: ds.name })}
                      data-testid="studio-scenario-check"
                    />
                  </td>
                  <td className="py-2 pr-3 font-medium">{ds.name}</td>
                  <td className="py-2 pr-3">
                    {launchPhases[ds.id] ? (
                      <span
                        className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs ${STATUS_TONE.pending}`}
                        data-testid="studio-scenario-launching"
                      >
                        <span className="h-2.5 w-2.5 animate-spin rounded-full border border-current border-t-transparent" />
                        {launchPhases[ds.id] === "compiling"
                          ? t("scenariosCompiling")
                          : t("scenariosQueueing")}
                      </span>
                    ) : failure ? (
                      <span
                        className={`inline-block max-w-[16rem] truncate rounded-full px-2 py-0.5 text-xs ${STATUS_TONE.failed}`}
                        title={failure}
                        data-testid="studio-scenario-failed"
                      >
                        {failure}
                      </span>
                    ) : run ? (
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs ${STATUS_TONE[run.status] ?? "bg-muted text-muted-foreground"}`}
                        title={run.error_message ?? undefined}
                      >
                        {run.status}
                      </span>
                    ) : (
                      <span className="text-xs text-muted-foreground">{t("scenariosNoRun")}</span>
                    )}
                  </td>
                  <td
                    className="py-2 pr-3 text-right font-mono tabular-nums"
                    data-testid="studio-scenario-objective"
                  >
                    {fmt(run?.objective_value)}
                  </td>
                  <td className="py-2 pr-3 text-right text-muted-foreground tabular-nums">
                    {run?.execution_time_ms != null ? `${run.execution_time_ms}ms` : "—"}
                  </td>
                  <td className="py-2 text-muted-foreground">
                    {run?.solver_name?.toUpperCase() ?? "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Always visible so the diff is discoverable — it used to materialize only
          once exactly 2 completed datasets were selected, and nobody could guess
          that rule from an absent button (live report 2026-07-04). */}
      <div className="mt-3 flex items-center gap-3">
        <Button
          variant="outline"
          size="sm"
          onClick={() => void handleCompare()}
          disabled={!comparable || diffLoading}
          title={!comparable ? t("scenariosCompareHint") : undefined}
          data-testid="studio-scenarios-compare"
        >
          <GitCompareArrows className="mr-1 h-3.5 w-3.5" />
          {t("scenariosCompare")}
        </Button>
        {!comparable && (
          <span className="text-xs text-muted-foreground">{t("scenariosCompareHint")}</span>
        )}
      </div>

      {diff && (
        <div className="mt-3 rounded-md border p-3" data-testid="studio-scenarios-diff">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            {t("scenariosDiffTitle", { a: diff.aName, b: diff.bName })}
          </h4>
          {diff.rows.length === 0 ? (
            <p className="mt-2 text-sm text-muted-foreground">{t("scenariosDiffIdentical")}</p>
          ) : (
            <>
              <table className="mt-2 w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th className="py-1.5 pr-3 font-medium">{t("scenariosDiffVariable")}</th>
                    <th className="py-1.5 pr-3 text-right font-medium">{diff.aName}</th>
                    <th className="py-1.5 text-right font-medium">{diff.bName}</th>
                  </tr>
                </thead>
                <tbody>
                  {diff.rows.map((row) => (
                    <tr key={row.name} className="border-b last:border-0">
                      <td className="py-1.5 pr-3 font-mono text-xs">{row.name}</td>
                      <td className="py-1.5 pr-3 text-right font-mono tabular-nums">
                        {fmt(row.a)}
                      </td>
                      <td className="py-1.5 text-right font-mono tabular-nums">{fmt(row.b)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {diff.hiddenCount > 0 && (
                <p className="mt-2 text-xs text-muted-foreground">
                  {t("scenariosDiffMore", { count: diff.hiddenCount })}
                </p>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}
