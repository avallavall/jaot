"use client";

import { useTranslations } from "next-intl";

import { HelpTooltip } from "@/components/ui/help-tooltip";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { capabilitiesOf, type SolverInfo } from "@/hooks/useSolvers";
import { solverDescription, solverDisplayName } from "@/lib/solver-display";

interface SolverSelectProps {
  id?: string;
  solverName: string;
  onSolverChange: (name: string) => void;
  availableSolvers: SolverInfo[];
  loading: boolean;
  /** Optional "?" tooltip text rendered next to the label. */
  help?: string;
}

/**
 * Solver picker.
 *
 * - Each entry shows the brand name plus its fixed one-line description.
 * - Disabled when `solver.available === false` (D-11 — Hexaly worker
 *   down → greyed-out option). The frontend does not render a maintenance
 *   tooltip; the disabled state is the contract.
 * - The "auto" option is always present and reachable, even when
 *   availableSolvers is empty.
 * - Below the select, it names what the CHOSEN solver will not deliver (v3.2),
 *   so the trade-off is visible before the solve rather than as an empty panel
 *   after it. Only the two consequences the user actually observes are called
 *   out — no shadow prices, and no progress while it runs. Quadratic support is
 *   a property of the MODEL (which this component does not see) and warm-start
 *   is an internal speed-up, so neither belongs in a pre-solve warning. "auto"
 *   says nothing at all: the backend picks the effective solver per problem.
 */
export function SolverSelect({
  id = "solver-select",
  solverName,
  onSolverChange,
  availableSolvers,
  loading,
  help,
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

  const chosen = capabilitiesOf(availableSolvers, solverName);
  const notices: string[] = [];
  if (chosen) {
    const display = solverDisplayName(solverName);
    if (!chosen.sensitivity) notices.push(tSolvers("noSensitivityNotice", { solver: display }));
    if (!chosen.progress) notices.push(tSolvers("noProgressNotice", { solver: display }));
  }

  // Even with zero available_solvers from the backend, we still render the
  // Select so the "auto" option is reachable — auto-routing falls back to
  // SCIP on the backend regardless.
  return (
    <div className="space-y-2 mb-4">
      <span className="inline-flex items-center gap-1">
        <Label htmlFor={id} className="text-sm text-muted-foreground">
          {tSolvers("selectLabel")}
        </Label>
        {help && <HelpTooltip content={help} size={12} />}
      </span>
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
              {solverDescription(solver.name, solver.description, tSolvers) && (
                <span className="text-muted-foreground text-xs ml-2">
                  {solverDescription(solver.name, solver.description, tSolvers)}
                </span>
              )}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {notices.length > 0 && (
        <ul className="space-y-0.5 text-xs text-muted-foreground" data-testid="solver-capability-notice">
          {notices.map((notice) => (
            <li key={notice}>{notice}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
