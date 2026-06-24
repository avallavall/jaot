"use client";

import { useTranslations } from "next-intl";

import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { SolverInfo } from "@/hooks/useSolvers";
import { solverDisplayName } from "@/lib/solver-display";

interface SolverSelectProps {
  id?: string;
  solverName: string;
  onSolverChange: (name: string) => void;
  availableSolvers: SolverInfo[];
  loading: boolean;
}

/**
 * Solver picker with multiplier badge per Phase 7.4 / D-12.
 *
 * - Each entry shows "Name · N×" where N comes from
 *   `solver.multiplier` (Plan 07 backend response).
 * - Disabled when `solver.available === false` (D-11 — Hexaly worker
 *   down → greyed-out option). The frontend does not render a maintenance
 *   tooltip; the disabled state is the contract.
 * - The "auto" option is always present and reachable, even when
 *   availableSolvers is empty.
 */
export function SolverSelect({
  id = "solver-select",
  solverName,
  onSolverChange,
  availableSolvers,
  loading,
}: SolverSelectProps) {
  const tSolvers = useTranslations("solvers");
  const tAuto = useTranslations("solvers.auto");

  if (loading && availableSolvers.length === 0) {
    return (
      <div className="space-y-2 mb-4">
        <Label className="text-sm text-muted-foreground">
          {tSolvers("selectLabel")}
        </Label>
        <Select disabled>
          <SelectTrigger className="w-full">
            <SelectValue placeholder={tSolvers("loadingLabel")} />
          </SelectTrigger>
          <SelectContent />
        </Select>
      </div>
    );
  }

  // Even with zero available_solvers from the backend, we still render the
  // Select so the "auto" option is reachable — auto-routing falls back to
  // SCIP on the backend regardless.
  return (
    <div className="space-y-2 mb-4">
      <Label htmlFor={id} className="text-sm text-muted-foreground">
        {tSolvers("selectLabel")}
      </Label>
      <Select
        value={solverName}
        onValueChange={onSolverChange}
        disabled={loading}
      >
        <SelectTrigger id={id} className="w-full">
          <SelectValue placeholder={tSolvers("selectPlaceholder")} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="auto">
            <span>{tAuto("label")}</span>
            <span className="text-muted-foreground text-xs ml-2">
              {tAuto("hint")}
            </span>
          </SelectItem>
          {availableSolvers.map((solver) => (
            <SelectItem
              key={solver.name}
              value={solver.name}
              disabled={solver.available === false}
            >
              <span>{solverDisplayName(solver.name)}</span>
              {solver.multiplier != null && (
                <span className="text-xs font-mono ml-2 text-muted-foreground">
                  {`${solver.multiplier}×`}
                </span>
              )}
              {solver.description && (
                <span className="text-muted-foreground text-xs ml-2">
                  {solver.description}
                </span>
              )}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
