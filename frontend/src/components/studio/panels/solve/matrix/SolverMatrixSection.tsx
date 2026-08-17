"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Grid3x3, Loader2, Play, X } from "lucide-react";

import { Link } from "@/i18n/navigation";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { HelpTooltip } from "@/components/ui/help-tooltip";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ComparisonTable } from "@/components/solve/compare/ComparisonTable";
import { useSolvers } from "@/hooks/useSolvers";
import { api } from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";
import type { ComparisonBatchDetail, ComparisonDetail } from "@/lib/types";
import { useModelProjectStore } from "../../../store/useModelProjectStore";
import { useProjectDatasets } from "../../../datasets/useProjectDatasets";
import { MatrixTable } from "./MatrixTable";
import {
  MATRIX_METRICS,
  type MatrixMetric,
  canStopMatrix,
  hardestRow,
  shouldKeepPollingMatrix,
  winnerCount,
} from "./matrix-metrics";

/** How often the grid refreshes while any cell is still being solved. The runs
 * are sequential, so nothing changes faster than one solver at a time. */
const POLL_INTERVAL_MS = 2000;

/** Mirrors MAX_DATASETS_PER_BATCH on the server. Checked here too so the user
 * is told before the request, not by a 422 after it. */
const MAX_DATASETS = 12;

/**
 * The solver matrix (phase 3): several of the model's datasets crossed with
 * several solvers, in one launch.
 *
 * The Scenarios section above answers "what does the answer look like under each
 * dataset". This one answers a different question — "which solver should I run
 * this model with" — and one dataset cannot answer it: the solver that wins on
 * January's data routinely loses on March's.
 *
 * The number of runs is the PRODUCT, not the sum, so the total and the worst
 * case are shown before launching and the launch asks for confirmation.
 */
export function SolverMatrixSection() {
  const t = useTranslations("studio");
  const modelId = useModelProjectStore((s) => s.modelId);
  const draftDslSource = useModelProjectStore((s) => s.draftDslSource);
  const isPersisted = !!modelId && modelId !== "new";
  const { datasets } = useProjectDatasets(isPersisted ? modelId : null);
  const { availableSolvers, solversLoading } = useSolvers();

  const [selectedDatasets, setSelectedDatasets] = useState<string[]>([]);
  const [selectedSolvers, setSelectedSolvers] = useState<string[]>([]);
  const [timeLimit, setTimeLimit] = useState(60);
  const [gapTolerance, setGapTolerance] = useState(0.0001);

  const [batch, setBatch] = useState<ComparisonBatchDetail | null>(null);
  const [starting, setStarting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [metric, setMetric] = useState<MatrixMetric>("time");
  const [openRow, setOpenRow] = useState<ComparisonDetail | null>(null);

  // Pre-select every dataset and every solver that can run: the common case is
  // "cross everything", and the server decides who can actually take part.
  const datasetsPreselected = useRef(false);
  useEffect(() => {
    if (datasetsPreselected.current || datasets.length === 0) return;
    datasetsPreselected.current = true;
    setSelectedDatasets(datasets.slice(0, MAX_DATASETS).map((dataset) => dataset.id));
  }, [datasets]);

  // Once, when the solver list arrives. Keyed on a ref rather than on "nothing is
  // selected", which would refill the boxes the moment the last one was unticked.
  const solversPreselected = useRef(false);
  useEffect(() => {
    if (solversPreselected.current || availableSolvers.length === 0) return;
    solversPreselected.current = true;
    setSelectedSolvers(availableSolvers.filter((s) => s.available).map((s) => s.name));
  }, [availableSolvers]);

  // The last matrix for this model, restored on mount. A grid of fifty runs takes
  // minutes; without this, leaving the tab lost it.
  useEffect(() => {
    if (!isPersisted) return;
    let cancelled = false;
    api.solverComparison.batches
      .list({ project_id: modelId, limit: 1 })
      .then((page) => {
        const latest = page.batches[0];
        if (!latest || cancelled) return;
        return api.solverComparison.batches.get(latest.batch_id).then((detail) => {
          if (!cancelled) setBatch(detail);
        });
      })
      .catch(() => {
        /* no history to restore — the section just starts empty */
      });
    return () => {
      cancelled = true;
    };
  }, [modelId, isPersisted]);

  const refresh = useCallback(async (batchId: string) => {
    try {
      setBatch(await api.solverComparison.batches.get(batchId));
    } catch {
      // A dropped poll is not worth a toast — the next tick retries.
    }
  }, []);

  const batchId = batch?.batch_id;
  const polling = shouldKeepPollingMatrix(batch);
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;

  useEffect(() => {
    if (!batchId || !polling) return;
    const timer = setInterval(() => void refreshRef.current(batchId), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [batchId, polling]);

  // Recomputed only when the grid or the metric changes, not on every render:
  // the page re-renders every two seconds while the matrix runs, and both walk
  // every cell of it.
  const winner = useMemo(() => (batch ? winnerCount(batch.rows, metric) : null), [batch, metric]);
  const hardest = useMemo(() => (batch ? hardestRow(batch.rows) : null), [batch]);

  const hasSource = draftDslSource.trim().length > 0;
  const runs = selectedDatasets.length * selectedSolvers.length;
  const canLaunch =
    hasSource && selectedDatasets.length > 0 && selectedSolvers.length > 0 && !starting;

  async function launch() {
    setConfirmOpen(false);
    setStarting(true);
    setOpenRow(null);
    try {
      setBatch(
        await api.solverComparison.batches.create({
          project_id: modelId,
          dataset_ids: selectedDatasets,
          solver_names: selectedSolvers,
          settings: { time_limit_seconds: timeLimit, gap_tolerance: gapTolerance },
        }),
      );
    } catch (error) {
      toast.error(getErrorMessage(error, t("matrix.launchFailed")));
    } finally {
      setStarting(false);
    }
  }

  async function stop() {
    if (!batch) return;
    try {
      setBatch(await api.solverComparison.batches.cancel(batch.batch_id));
    } catch (error) {
      toast.error(getErrorMessage(error, t("matrix.cancelFailed")));
    }
  }

  async function openComparison(comparisonId: string) {
    if (openRow?.id === comparisonId) {
      setOpenRow(null);
      return;
    }
    try {
      setOpenRow(await api.solverComparison.get(comparisonId));
    } catch (error) {
      toast.error(getErrorMessage(error, t("matrix.rowFailed")));
    }
  }

  if (!isPersisted || datasets.length === 0) return null;

  return (
    <section
      data-testid="studio-matrix"
      className="mx-auto mt-8 w-full max-w-3xl rounded-lg border p-4"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold">
            <Grid3x3 className="h-4 w-4 text-muted-foreground" />
            {t("matrix.title")}
            <HelpTooltip content={t("matrix.help")} size={12} />
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">{t("matrix.hint")}</p>
        </div>
        {canStopMatrix(batch) ? (
          <Button size="sm" variant="outline" onClick={() => void stop()} className="shrink-0">
            <X className="mr-1 h-3.5 w-3.5" />
            {t("matrix.stop")}
          </Button>
        ) : (
          <Button
            size="sm"
            onClick={() => setConfirmOpen(true)}
            disabled={!canLaunch}
            data-testid="studio-matrix-launch"
            className="shrink-0"
          >
            {starting ? (
              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="mr-1 h-3.5 w-3.5" />
            )}
            {t("matrix.launch", { runs })}
          </Button>
        )}
      </div>

      {!hasSource && (
        <p
          className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200"
          data-testid="studio-matrix-needs-jmodel"
        >
          {t("matrix.needsJModel")}{" "}
          <Link
            href={`/studio/${modelId}/build?lens=jmodel`}
            className="font-medium underline underline-offset-2"
          >
            {t("scenariosOpenJModel")}
          </Link>
        </p>
      )}

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <fieldset className="space-y-2">
          <legend className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            {t("matrix.datasetsLabel")}
          </legend>
          <div className="max-h-40 space-y-1.5 overflow-y-auto pr-1">
            {datasets.map((dataset) => {
              const checked = selectedDatasets.includes(dataset.id);
              const full = selectedDatasets.length >= MAX_DATASETS;
              return (
                <label key={dataset.id} className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={checked}
                    disabled={!checked && full}
                    onCheckedChange={(next) =>
                      setSelectedDatasets((current) =>
                        next
                          ? [...current, dataset.id]
                          : current.filter((id) => id !== dataset.id),
                      )
                    }
                    data-testid="studio-matrix-dataset"
                  />
                  <span className="truncate">{dataset.name}</span>
                </label>
              );
            })}
          </div>
          {datasets.length > MAX_DATASETS && (
            <p className="text-xs text-muted-foreground">
              {t("matrix.datasetCap", { max: MAX_DATASETS })}
            </p>
          )}
        </fieldset>

        <fieldset className="space-y-2">
          <legend className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            {t("matrix.solversLabel")}
          </legend>
          {solversLoading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <div className="space-y-1.5">
              {availableSolvers
                .filter((solver) => solver.available)
                .map((solver) => (
                  <label key={solver.name} className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={selectedSolvers.includes(solver.name)}
                      onCheckedChange={(next) =>
                        setSelectedSolvers((current) =>
                          next
                            ? [...current, solver.name]
                            : current.filter((name) => name !== solver.name),
                        )
                      }
                      data-testid="studio-matrix-solver"
                    />
                    <span className="uppercase">{solver.name}</span>
                  </label>
                ))}
            </div>
          )}
        </fieldset>
      </div>

      <div className="mt-4 flex flex-wrap items-end gap-4">
        <div className="space-y-1">
          <Label htmlFor="matrix-time-limit" className="text-xs">
            {t("matrix.timeLimitLabel")}
          </Label>
          <Input
            id="matrix-time-limit"
            type="number"
            min={1}
            className="w-32"
            value={timeLimit}
            onChange={(event) => setTimeLimit(Number(event.target.value))}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="matrix-gap" className="text-xs">
            {t("matrix.gapLabel")}
          </Label>
          <Input
            id="matrix-gap"
            type="number"
            min={0}
            max={1}
            step={0.0001}
            className="w-32"
            value={gapTolerance}
            onChange={(event) => setGapTolerance(Number(event.target.value))}
          />
        </div>
        {/* The wait is the product AND the sum: every run waits for the one
            before it, which is what keeps the seconds comparable. */}
        <p className="text-xs text-muted-foreground" data-testid="studio-matrix-estimate">
          {t("matrix.estimate", { runs, minutes: Math.ceil((runs * timeLimit) / 60) })}
        </p>
      </div>

      {batch && (
        <div className="mt-6 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground" data-testid="studio-matrix-status">
              {t(`matrix.status.${batch.status}`)}
            </p>
            <div className="flex items-center gap-2">
              <Label htmlFor="matrix-metric" className="text-xs">
                {t("matrix.metricLabel")}
              </Label>
              <Select value={metric} onValueChange={(next) => setMetric(next as MatrixMetric)}>
                <SelectTrigger id="matrix-metric" className="h-8 w-44 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MATRIX_METRICS.map((name) => (
                    <SelectItem key={name} value={name}>
                      {t(`matrix.metric.${name}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <MatrixTable
            batch={batch}
            metric={metric}
            openRow={openRow?.id ?? null}
            onOpenRow={(comparisonId) => void openComparison(comparisonId)}
          />

          <div className="space-y-1 text-xs text-muted-foreground">
            {winner ? (
              <p data-testid="studio-matrix-winner">
                {t("matrix.winner", {
                  solver: winner.solver.toUpperCase(),
                  metric: t(`matrix.metric.${metric}`),
                  wins: winner.wins,
                  total: winner.rowsCompared,
                })}
              </p>
            ) : null}
            {hardest ? (
              <p data-testid="studio-matrix-hardest">
                {t("matrix.hardest", { dataset: hardest.dataset_name ?? "" })}
              </p>
            ) : null}
            {/* Seconds are comparable inside one matrix and nowhere else: one
                machine, one run at a time. */}
            <p>{t("matrix.scope")}</p>
            {batch.machine_note ? (
              <p>
                {t("matrix.machineLabel")}{" "}
                <span className="font-mono">{batch.machine_note}</span>
              </p>
            ) : null}
          </div>

          {openRow ? (
            <div className="rounded-lg border p-3" data-testid="studio-matrix-open-row-detail">
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                {openRow.dataset_name ?? openRow.problem_name}
              </h4>
              <ComparisonTable comparison={openRow} />
            </div>
          ) : null}
        </div>
      )}

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("matrix.confirmTitle", { runs })}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("matrix.confirmBody", {
                runs,
                datasets: selectedDatasets.length,
                solvers: selectedSolvers.length,
                minutes: Math.ceil((runs * timeLimit) / 60),
              })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("matrix.confirmCancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => void launch()}
              data-testid="studio-matrix-confirm"
            >
              {t("matrix.confirmRun")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
