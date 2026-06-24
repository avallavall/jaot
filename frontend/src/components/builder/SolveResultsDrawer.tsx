"use client";

// SolveResultsDrawer — Displays optimization results after solve
// Uses a right-side panel (Dialog-based sheet pattern)

import { useEffect, useRef } from "react";
import type { SolveResult } from "@/lib/types";
import { SensitivityTab } from "@/components/solve/SensitivityTab";
import { SolverDisclaimer } from "@/components/legal/SolverDisclaimer";
import { HelpTooltip } from "@/components/ui/help-tooltip";
import { Button } from "@/components/ui/button";
import { useTranslations } from "next-intl";

interface SolveResultsDrawerProps {
  result: SolveResult | null;
  isOpen: boolean;
  onClose: () => void;
}

function StatusBadge({ status }: { status: string }) {
  const variants: Record<string, string> = {
    optimal: "bg-[var(--status-optimal-bg)] text-[var(--status-optimal-text)] border-[var(--status-optimal-border)]",
    feasible: "bg-[var(--status-feasible-bg)] text-[var(--status-feasible-text)] border-[var(--status-feasible-border)]",
    infeasible: "bg-[var(--status-infeasible-bg)] text-[var(--status-infeasible-text)] border-[var(--status-infeasible-border)]",
    unbounded: "bg-[var(--status-unbounded-bg)] text-[var(--status-unbounded-text)] border-[var(--status-unbounded-border)]",
    time_limit: "bg-[var(--status-timelimit-bg)] text-[var(--status-timelimit-text)] border-[var(--status-timelimit-border)]",
    error: "bg-[var(--status-error-bg)] text-[var(--status-error-text)] border-[var(--status-error-border)]",
  };
  const className = variants[status] ?? "bg-muted text-muted-foreground border-border";

  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 text-xs font-semibold border ${className}`}
    >
      {status.replace("_", " ").toUpperCase()}
    </span>
  );
}

function StatusExplanation({ status }: { status: string }) {
  const t = useTranslations("builder");
  const explanationKeys: Record<string, string> = {
    infeasible: "results.statusInfeasible",
    unbounded: "results.statusUnbounded",
    time_limit: "results.statusTimeLimit",
    error: "results.statusError",
  };

  const key = explanationKeys[status];
  const explanation = key ? t(key) : null;
  if (!explanation) return null;

  return (
    <div className="mt-3 p-3 bg-[var(--status-timelimit-bg)] border border-[var(--status-timelimit-border)] rounded-md text-sm text-[var(--status-timelimit-text)]">
      {explanation}
    </div>
  );
}

export function SolveResultsDrawer({ result, isOpen, onClose }: SolveResultsDrawerProps) {
  const t = useTranslations("builder");
  const tHelp = useTranslations("solve.helpTooltips");
  const drawerRef = useRef<HTMLDivElement>(null);

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen || !result) return null;

  const hasVariables = result.variables && result.variables.length > 0;
  const isSuccess = result.status === "optimal" || result.status === "feasible";

  return (
    <>
      <div
        className="fixed inset-0 bg-black/20 z-40"
        onClick={onClose}
        aria-hidden="true"
      />

      <div
        ref={drawerRef}
        className="fixed right-0 top-0 h-full w-96 bg-background border-l shadow-xl z-50 flex flex-col"
        role="dialog"
        aria-modal="true"
        aria-label={t("results.title")}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b shrink-0">
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold">{t("results.title")}</h2>
            <StatusBadge status={result.status} />
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} className="h-7 w-7 p-0" aria-label={t("results.closeDrawer")}>
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          <StatusExplanation status={result.status} />

          {isSuccess && result.objective_value !== undefined && result.objective_value !== null && (
            <div className="p-3 bg-muted rounded-lg">
              <p className="text-xs text-muted-foreground uppercase tracking-wider font-medium mb-1">
                {t("results.objectiveValue")}
              </p>
              <p className="text-2xl font-bold tabular-nums">
                {result.objective_value.toFixed(4)}
              </p>
            </div>
          )}

          {isSuccess && hasVariables && (
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wider font-medium mb-2">
                {t("results.variableAssignments")}
              </p>
              <div className="border rounded-md overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-muted/50">
                      <th className="text-left px-3 py-2 font-medium text-muted-foreground">{t("results.variable")}</th>
                      <th className="text-right px-3 py-2 font-medium text-muted-foreground">{t("results.value")}</th>
                      <th className="text-right px-3 py-2 font-medium text-muted-foreground">{t("results.type")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(result.variables ?? []).map((v, i) => (
                      <tr key={v.name} className={i % 2 === 0 ? "" : "bg-muted/20"}>
                        <td className="px-3 py-2 font-mono font-medium">{v.name}</td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {typeof v.value === "number" ? v.value.toFixed(4) : String(v.value)}
                        </td>
                        <td className="px-3 py-2 text-right">
                          <span className="text-xs text-muted-foreground">{v.type}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wider font-medium mb-2">
              {t("results.performance")}
            </p>
            <div className="space-y-1.5 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">{t("results.solveTime")}</span>
                <span className="tabular-nums font-medium">
                  {result.solve_time_seconds
                    ? `${(result.solve_time_seconds * 1000).toFixed(0)} ms`
                    : "—"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">{t("results.creditsUsed")}</span>
                <span className="tabular-nums font-medium">{result.credits_used}</span>
              </div>
              {result.credits_remaining !== undefined && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">{t("results.creditsRemaining")}</span>
                  <span className="tabular-nums font-medium">{result.credits_remaining}</span>
                </div>
              )}
              {result.gap !== undefined && result.gap !== null && (
                <div className="flex justify-between">
                  <span className="text-muted-foreground">{t("results.mipGap")}</span>
                  <span className="tabular-nums font-medium">{(result.gap * 100).toFixed(3)}%</span>
                </div>
              )}
            </div>
          </div>

          {result.error_message && (
            <div className="p-3 bg-[var(--status-error-bg)] border border-[var(--status-error-border)] rounded-md">
              <p className="text-xs font-medium text-[var(--status-error-text)] mb-1">{t("results.errorDetails")}</p>
              <p className="text-xs text-[var(--status-error-text)] font-mono break-all">{result.error_message}</p>
            </div>
          )}

          <div className="space-y-2">
            <p className="text-xs text-muted-foreground uppercase tracking-wider font-medium flex items-center gap-1.5">
              {t("results.sensitivityAnalysis")}
              <HelpTooltip content={tHelp("sensitivityAnalysis")} side="right" size={13} />
            </p>
            {result.sensitivity ? (
              <SensitivityTab sensitivity={result.sensitivity} />
            ) : (
              <div className="p-3 bg-muted/50 rounded-lg border border-dashed">
                <p className="text-sm text-muted-foreground">
                  {t("results.sensitivityUnavailable")}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  {t("results.sensitivityNote")}
                </p>
              </div>
            )}
          </div>

          <SolverDisclaimer />
        </div>

        <div className="border-t px-4 py-3 shrink-0">
          <Button onClick={onClose} className="w-full" variant="outline" size="sm">
            Close
          </Button>
        </div>
      </div>
    </>
  );
}
