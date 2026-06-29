"use client";

import { useMemo, useState } from "react";
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
import type { SolveResult } from "@/lib/types";
import { useModelProjectStore } from "../store/useModelProjectStore";
import { solveBlockedReason } from "./solve-precondition";
import { LiveSolvePanel } from "./solve/LiveSolvePanel";

/**
 * The Solve lens. Runs the CANONICAL model (from the shared store) through the
 * ASYNC `/solve/async` endpoint so progress streams live (Live Solve), shows the
 * real-time convergence chart, and opens the shared results drawer when it finishes.
 * Provenance is tagged `source_kind="model_project"` so the run traces back to this
 * project. (The synchronous `/solve` stays the API/ERP path — only the workspace UI is async.)
 */
export function SolvePanel() {
  const t = useTranslations("studio");
  const problem = useModelProjectStore((s) => s.problem);
  const modelId = useModelProjectStore((s) => s.modelId);
  const { activeWorkspaceId } = useAuth();
  const canSolve = useWorkspacePermission("solver");
  const { solverName, setSolverName, availableSolvers, solversLoading } = useSolvers();
  const [solving, setSolving] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [result, setResult] = useState<SolveResult | null>(null);
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

  const handleSolve = async () => {
    if (blocked) return;
    setSolving(true);
    setResult(null);
    setTaskId(null);
    try {
      const sourceId = modelId && modelId !== "new" ? modelId : null;
      const task = await api.solveAsync(
        { ...problem, solver_name: solverName },
        activeWorkspaceId ?? undefined,
        { origin: "visual_builder", sourceKind: "model_project", sourceId }
      );
      setTaskId(task.task_id);
    } catch (err: unknown) {
      const status = getErrorStatus(err);
      if (status === 402) {
        toast.error(t("solveInsufficientCredits"));
      } else if (status === 422) {
        toast.error(getErrorMessage(err, t("solveInvalid")));
      } else {
        toast.error(getErrorMessage(err, t("solveFailed")));
      }
      setSolving(false);
    }
  };

  const disabled = solving || !canSolve || blocked !== null;

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
                <Button onClick={handleSolve} disabled={disabled} className="w-full">
                  <Play className="mr-1 h-4 w-4" />
                  {solving ? t("solveRunning") : t("headerSolve")}
                </Button>
              </span>
            </TooltipTrigger>
            {blockedLabel && <TooltipContent>{blockedLabel}</TooltipContent>}
          </Tooltip>
        </TooltipProvider>

        {taskId && (
          <LiveSolvePanel
            taskId={taskId}
            objectiveSense={objectiveSense}
            onComplete={(res) => {
              setResult(res);
              setSolving(false);
            }}
            onError={(message) => {
              toast.error(message);
              setSolving(false);
            }}
            onCancelled={() => setSolving(false)}
          />
        )}

        {result && (
          <Button
            variant="outline"
            className="w-full"
            onClick={() => setDrawerOpen(true)}
          >
            {t("solveViewResults")}
          </Button>
        )}
      </div>

      <SolveResultsDrawer
        result={result}
        isOpen={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
}
