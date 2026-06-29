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

/**
 * The Solve lens. Runs the CANONICAL model (from the shared store, not a fresh
 * canvas serialize) through the universal `/solve` endpoint, with a solver picker
 * and the shared results drawer. Provenance uses the builder-document shape until
 * ModelProject-origin solves land in P2.
 */
export function SolvePanel() {
  const t = useTranslations("studio");
  const problem = useModelProjectStore((s) => s.problem);
  const modelId = useModelProjectStore((s) => s.modelId);
  const { activeWorkspaceId } = useAuth();
  const canSolve = useWorkspacePermission("solver");
  const { solverName, setSolverName, availableSolvers, solversLoading } = useSolvers();
  const [isSolving, setIsSolving] = useState(false);
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

  const handleSolve = async () => {
    if (blocked) return;
    setIsSolving(true);
    try {
      const sourceId = modelId && modelId !== "new" ? modelId : null;
      const res = await api.solve(
        { ...problem, solver_name: solverName },
        activeWorkspaceId ?? undefined,
        { origin: "visual_builder", sourceKind: "builder_document", sourceId }
      );
      setResult(res);
      setDrawerOpen(true);
    } catch (err: unknown) {
      const status = getErrorStatus(err);
      if (status === 402) {
        toast.error(t("solveInsufficientCredits"));
      } else if (status === 422) {
        toast.error(getErrorMessage(err, t("solveInvalid")));
      } else {
        toast.error(getErrorMessage(err, t("solveFailed")));
      }
    } finally {
      setIsSolving(false);
    }
  };

  const disabled = isSolving || !canSolve || blocked !== null;

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
                  {isSolving ? t("solveRunning") : t("headerSolve")}
                </Button>
              </span>
            </TooltipTrigger>
            {blockedLabel && <TooltipContent>{blockedLabel}</TooltipContent>}
          </Tooltip>
        </TooltipProvider>

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
