"use client";

import { useState, useEffect } from "react";
import { api, ModelExecution } from "@/lib/api";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useTranslations } from "next-intl";

export interface WarmStartCandidateInfo {
  id: string;
  objective_value?: number;
  solver_status: "optimal" | "feasible";
  created_at: string;
  variable_count: number;
}

interface WarmStartDropdownProps {
  modelId: string;
  onSelect: (executionId: string | null, info?: WarmStartCandidateInfo) => void;
  selectedId?: string | null;
  /** Increment to trigger a refetch (e.g. after a solve completes) */
  refreshKey?: number;
}

type WarmStartCandidate = ModelExecution & {
  solver_status: "optimal" | "feasible";
};

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatObjective(value: number | undefined): string {
  if (value === undefined || value === null) return "N/A";
  return value.toFixed(4);
}

function getVariableCount(candidate: WarmStartCandidate): number {
  const result = candidate.result_data as
    | { solution?: Record<string, unknown>; variables?: unknown[] }
    | undefined;
  if (!result) return 0;
  if (result.solution) return Object.keys(result.solution).length;
  if (result.variables) return result.variables.length;
  return 0;
}

function StatusBadge({ status }: { status: "optimal" | "feasible" }) {
  const styles =
    status === "optimal"
      ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
      : "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400";
  return (
    <span
      className={`inline-block px-1 py-0.5 rounded text-[0.5625rem] font-semibold uppercase tracking-wide ${styles}`}
    >
      {status}
    </span>
  );
}

export function WarmStartDropdown({
  modelId,
  onSelect,
  selectedId,
  refreshKey = 0,
}: WarmStartDropdownProps) {
  const t = useTranslations("solve.warmStart");
  const [candidates, setCandidates] = useState<WarmStartCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchCandidates() {
      setLoading(true);
      setError(null);
      try {
        // Fetch recent executions (up to 50, then filter client-side)
        const response = await api.getModelExecutions(modelId, {
          page: 1,
          page_size: 50,
        });
        const eligible = response.items.filter(
          (e): e is WarmStartCandidate =>
            e.status === "completed" &&
            (e.solver_status === "optimal" || e.solver_status === "feasible")
        );
        // Sort by created_at descending (most recent first)
        eligible.sort(
          (a, b) =>
            new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
        );
        setCandidates(eligible);
      } catch (err) {
        setError(err instanceof Error ? err.message : t("couldNotLoad"));
      } finally {
        setLoading(false);
      }
    }

    fetchCandidates();
  }, [modelId, t, refreshKey]);

  const handleValueChange = (value: string) => {
    if (value === "__none__") {
      onSelect(null);
    } else {
      const candidate = candidates.find((c) => c.id === value);
      const info: WarmStartCandidateInfo | undefined = candidate
        ? {
            id: candidate.id,
            objective_value: candidate.objective_value,
            solver_status: candidate.solver_status,
            created_at: candidate.created_at,
            variable_count: getVariableCount(candidate),
          }
        : undefined;
      onSelect(value, info);
    }
  };

  if (loading) {
    return (
      <div className="w-full h-10 bg-muted animate-pulse rounded-md" />
    );
  }

  if (error) {
    return (
      <div className="text-xs text-muted-foreground px-1">
        {t("couldNotLoad")}
      </div>
    );
  }

  if (candidates.length === 0) {
    return (
      <div className="text-xs text-muted-foreground px-1">
        {t("noCandidates")}
      </div>
    );
  }

  const currentValue = selectedId ?? "__none__";

  return (
    <Select value={currentValue} onValueChange={handleValueChange}>
      <SelectTrigger className="w-full text-sm">
        <SelectValue placeholder={t("nonePlaceholder")} />
      </SelectTrigger>
      <SelectContent className="max-w-[480px]">
        <SelectItem value="__none__">
          <span className="text-muted-foreground">{t("nonePlaceholder")}</span>
        </SelectItem>
        {candidates.map((candidate) => (
          <SelectItem key={candidate.id} value={candidate.id}>
            <span className="flex flex-col gap-0.5">
              <span className="flex items-center gap-2 text-sm">
                <StatusBadge status={candidate.solver_status} />
                <span className="font-mono text-xs text-muted-foreground">
                  {formatDate(candidate.created_at)}
                </span>
              </span>
              <span className="flex items-center gap-3 text-xs text-muted-foreground">
                <span>
                  Obj: <span className="font-mono text-foreground">{formatObjective(candidate.objective_value)}</span>
                </span>
                {getVariableCount(candidate) > 0 && (
                  <span>
                    {t("variables", { count: getVariableCount(candidate) })}
                  </span>
                )}
                {candidate.execution_time_ms !== undefined && (
                  <span>
                    Time: <span className="font-mono text-foreground">{candidate.execution_time_ms}ms</span>
                  </span>
                )}
              </span>
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
