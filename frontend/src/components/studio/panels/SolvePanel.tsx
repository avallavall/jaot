"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { useFormatter, useNow, useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { SolverSelect } from "@/components/solve/SolverSelect";
import { SolveResultsDrawer } from "@/components/builder/SolveResultsDrawer";
import { useSolvers } from "@/hooks/useSolvers";
import { useAuth } from "@/contexts/AuthContext";
import { useWorkspacePermission } from "@/hooks/useWorkspacePermission";
import { api } from "@/lib/api";
import { getErrorMessage, getErrorStatus } from "@/lib/errors";
import { apiDate } from "@/lib/dates";
import { useModelProjectStore } from "../store/useModelProjectStore";
import { solveBlockedReason } from "./solve-precondition";
import { ProjectRunsCard } from "./solve/ProjectRunsCard";
import { ScenariosSection } from "./solve/ScenariosSection";
import { LiveSolvePanel } from "./solve/LiveSolvePanel";

/**
 * The Solve lens — a thin VIEW over the store's `solveSession`. The running solve
 * (polling + WS + accumulated points) is driven by `useSolveSession` at the provider
 * level, so it SURVIVES tab switches: this panel can unmount and remount and the
 * session keeps going. Runs the canonical model through async `/solve/async`,
 * tagged `source_kind="model_project"`.
 */
export function SolvePanel() {
  const t = useTranslations("studio");
  const format = useFormatter();
  const now = useNow();
  const problem = useModelProjectStore((s) => s.problem);
  const modelId = useModelProjectStore((s) => s.modelId);
  const scratchParseError = useModelProjectStore((s) => s.parseErrors.scratch ?? false);
  const dslParseError = useModelProjectStore((s) => s.parseErrors.dsl ?? false);
  const hasParseError = scratchParseError || dslParseError;
  const activeDataset = useModelProjectStore((s) => s.activeDataset);
  const session = useModelProjectStore((s) => s.solveSession);
  const lastRun = useModelProjectStore((s) => s.lastRun);
  const startSolveSession = useModelProjectStore((s) => s.startSolveSession);
  const clearSolveSession = useModelProjectStore((s) => s.clearSolveSession);
  const cancelSolveSession = useModelProjectStore((s) => s.cancelSolveSession);
  const { activeWorkspaceId } = useAuth();
  const canSolve = useWorkspacePermission("solver");
  const { solverName, setSolverName, availableSolvers, solversLoading } = useSolvers();
  const [submitting, setSubmitting] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const blocked = useMemo(() => solveBlockedReason(problem), [problem]);
  const blockedLabel = scratchParseError
    ? t("editorBlockSolve")
    : dslParseError
      ? t("jmodelBlockSolve")
      : blocked === "noVariables"
      ? t("solveNoVariables")
      : blocked === "noObjective"
        ? t("solveNoObjective")
        : !canSolve
          ? t("solveNoPermission")
          : null;

  const objectiveSense = problem.objective?.sense === "maximize" ? "maximize" : "minimize";
  const running = session.status === "running";
  const done = session.status === "done";

  // The reconciled "last run" banner — shown only when no live session owns the
  // panel, so a finished-while-away solve reads as "resuelta · objetivo X · hace Ys".
  const showLastRun = session.status === "idle" && lastRun !== null;
  const lastRunWhen =
    lastRun?.finishedAt != null ? format.relativeTime(apiDate(lastRun.finishedAt), now) : "";

  // Toast once when a solve fails.
  const failedRef = useRef(false);
  useEffect(() => {
    if (session.status === "failed" && !failedRef.current) {
      failedRef.current = true;
      toast.error(
        session.error && session.error !== "solveFailed" ? session.error : t("solveFailed"),
      );
    }
    if (session.status !== "failed") failedRef.current = false;
  }, [session.status, session.error, t]);

  const handleSolve = async () => {
    if (blocked || running || submitting || hasParseError) return;
    setSubmitting(true);
    clearSolveSession();
    try {
      const sourceId = modelId && modelId !== "new" ? modelId : null;
      const task = await api.solveAsync(
        { ...problem, solver_name: solverName },
        activeWorkspaceId ?? undefined,
        {
          origin: "visual_builder",
          sourceKind: "model_project",
          sourceId,
          // §8/S1: tag the run with the dataset the model was compiled against
          // so the executions history can say which scenario each run used.
          datasetId: activeDataset?.id ?? null,
        },
      );
      startSolveSession(task.task_id, solverName, new Date().toISOString());
    } catch (err: unknown) {
      const status = getErrorStatus(err);
      if (status === 422) toast.error(getErrorMessage(err, t("solveInvalid")));
      else toast.error(getErrorMessage(err, t("solveFailed")));
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = async () => {
    if (!session.taskId) return;
    try {
      await api.cancelSolveAsync(session.taskId);
    } catch {
      // best-effort; the poller still resolves the run
    }
    cancelSolveSession();
  };

  const disabled =
    submitting || running || !canSolve || blocked !== null || hasParseError;

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="mx-auto w-full max-w-xl space-y-4">
        <SolverSelect
          solverName={solverName}
          onSolverChange={setSolverName}
          availableSolvers={availableSolvers}
          loading={solversLoading}
          help={t("helpTooltips.solverAuto")}
        />

        {/* Which dataset (scenario) the canonical model was compiled against (§8).
            S4: the chip links to the Datos tab, where the selection is managed. */}
        {activeDataset && (
          <Link
            href={`/studio/${modelId}/data`}
            data-testid="studio-solve-dataset-chip"
            className="block rounded-md border border-emerald-200 bg-emerald-50 px-4 py-2 text-xs text-emerald-800 hover:bg-emerald-100 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200 dark:hover:bg-emerald-950/60"
          >
            {t("solveWithDataset", { name: activeDataset.name })}
          </Link>
        )}

        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="block">
                <Button
                  data-testid="studio-solve-run"
                  onClick={handleSolve}
                  disabled={disabled}
                  className="w-full"
                >
                  <Play className="mr-1 h-4 w-4" />
                  {running || submitting ? t("solveRunning") : t("headerSolve")}
                </Button>
              </span>
            </TooltipTrigger>
            {blockedLabel && <TooltipContent>{blockedLabel}</TooltipContent>}
          </Tooltip>
        </TooltipProvider>

        {showLastRun && lastRun && (
          <div
            data-testid="studio-last-run"
            className="rounded-md border bg-muted/40 px-4 py-3 text-sm text-muted-foreground"
          >
            {t("lastRun", {
              status: lastRun.status,
              hasObjective: lastRun.objectiveValue != null ? "yes" : "no",
              objective: lastRun.objectiveValue ?? 0,
              when: lastRunWhen,
            })}
          </div>
        )}

        {session.status !== "idle" && (
          <LiveSolvePanel
            session={session}
            objectiveSense={objectiveSense}
            onCancel={handleCancel}
          />
        )}

        {done && session.result && (
          <Button
            data-testid="studio-solve-done"
            variant="outline"
            className="w-full"
            onClick={() => setDrawerOpen(true)}
          >
            {t("solveViewResults")}
          </Button>
        )}
      </div>

      {/* S3: run the JModel against N datasets and compare outcomes side by side. */}
      <ScenariosSection solverName={solverName} />

      {/* This model's own run history (the global one lives under Solve → Executions). */}
      <ProjectRunsCard />

      <SolveResultsDrawer
        result={session.result}
        isOpen={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
}
