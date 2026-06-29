"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
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
import { useModelProjectStore } from "../store/useModelProjectStore";
import { solveBlockedReason } from "./solve-precondition";
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
  const problem = useModelProjectStore((s) => s.problem);
  const modelId = useModelProjectStore((s) => s.modelId);
  const session = useModelProjectStore((s) => s.solveSession);
  const startSolveSession = useModelProjectStore((s) => s.startSolveSession);
  const clearSolveSession = useModelProjectStore((s) => s.clearSolveSession);
  const cancelSolveSession = useModelProjectStore((s) => s.cancelSolveSession);
  const { activeWorkspaceId } = useAuth();
  const canSolve = useWorkspacePermission("solver");
  const { solverName, setSolverName, availableSolvers, solversLoading } = useSolvers();
  const [submitting, setSubmitting] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const blocked = useMemo(() => solveBlockedReason(problem), [problem]);
  const blockedLabel =
    blocked === "noVariables"
      ? t("solveNoVariables")
      : blocked === "noObjective"
        ? t("solveNoObjective")
        : !canSolve
          ? t("solveNoPermission")
          : null;

  const objectiveSense = problem.objective?.sense === "maximize" ? "maximize" : "minimize";
  const running = session.status === "running";
  const done = session.status === "done";

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
    if (blocked || running || submitting) return;
    setSubmitting(true);
    clearSolveSession();
    try {
      const sourceId = modelId && modelId !== "new" ? modelId : null;
      const task = await api.solveAsync(
        { ...problem, solver_name: solverName },
        activeWorkspaceId ?? undefined,
        { origin: "visual_builder", sourceKind: "model_project", sourceId },
      );
      startSolveSession(task.task_id, solverName);
    } catch (err: unknown) {
      const status = getErrorStatus(err);
      if (status === 402) toast.error(t("solveInsufficientCredits"));
      else if (status === 422) toast.error(getErrorMessage(err, t("solveInvalid")));
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

  const disabled = submitting || running || !canSolve || blocked !== null;

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="mx-auto w-full max-w-xl space-y-4">
        <SolverSelect
          solverName={solverName}
          onSolverChange={setSolverName}
          availableSolvers={availableSolvers}
          loading={solversLoading}
        />

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

      <SolveResultsDrawer
        result={session.result}
        isOpen={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
}
