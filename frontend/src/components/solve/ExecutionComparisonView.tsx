"use client";

import type { ModelExecution, OptimizationResult, VariableType } from "@/lib/types";
import { OriginBadge } from "@/components/solve/OriginBadge";
import { extractVariables } from "@/lib/result-utils";
import { useTranslations } from "next-intl";

interface ComparedVariable {
  name: string;
  type: VariableType;
  valueA: number | null;
  valueB: number | null;
  delta: number | null;
  changeType: "same" | "changed" | "added" | "removed";
}

interface ExecutionComparisonViewProps {
  executionA: ModelExecution;
  executionB: ModelExecution;
}

// ──────────────────────────────────────────────────────────────
// ──────────────────────────────────────────────────────────────

function formatValue(v: number | null): string {
  if (v === null) return "—";
  return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function formatDelta(delta: number | null): string {
  if (delta === null) return "";
  const sign = delta >= 0 ? "+" : "";
  return `${sign}${delta.toLocaleString(undefined, { maximumFractionDigits: 4 })}`;
}

function formatMs(ms: number): string {
  const sign = ms >= 0 ? "+" : "";
  return `${sign}${ms.toLocaleString()} ms`;
}

function formatObjDelta(delta: number, sense: string | undefined): { text: string; color: string } {
  const sign = delta >= 0 ? "+" : "";
  const text = `${sign}${delta.toLocaleString(undefined, { maximumFractionDigits: 4 })}`;
  // For minimize: negative delta = improved (green). For maximize: positive delta = improved (green).
  const isImproved =
    sense === "maximize" ? delta > 0 : sense === "minimize" ? delta < 0 : null;
  const color =
    isImproved === null
      ? "text-foreground"
      : isImproved
        ? "text-green-600 dark:text-green-400"
        : "text-red-600 dark:text-red-400";
  return { text, color };
}

function buildComparedVariables(
  execA: ModelExecution,
  execB: ModelExecution
): ComparedVariable[] {
  const varsA = extractVariables(execA.result_data as Record<string, unknown> | undefined);
  const varsB = extractVariables(execB.result_data as Record<string, unknown> | undefined);

  const mapA = new Map(varsA.map((v) => [v.name, v]));
  const mapB = new Map(varsB.map((v) => [v.name, v]));

  // Union of all variable names, sorted alphabetically
  const allNames = Array.from(new Set([...mapA.keys(), ...mapB.keys()])).sort();

  return allNames.map((name): ComparedVariable => {
    const varA = mapA.get(name);
    const varB = mapB.get(name);
    const valueA = varA != null ? Number(varA.value) : null;
    const valueB = varB != null ? Number(varB.value) : null;
    const type = ((varA ?? varB)!.type as VariableType) ?? "continuous";

    let delta: number | null = null;
    let changeType: ComparedVariable["changeType"];

    if (varA == null) {
      changeType = "added";
    } else if (varB == null) {
      changeType = "removed";
    } else {
      delta = valueB! - valueA!;
      changeType = Math.abs(delta) < 1e-10 ? "same" : "changed";
    }

    return { name, type, valueA, valueB, delta, changeType };
  });
}

function rowBgClass(changeType: ComparedVariable["changeType"]): string {
  switch (changeType) {
    case "changed":
      return "bg-yellow-50 dark:bg-yellow-950";
    case "added":
      return "bg-green-50 dark:bg-green-950";
    case "removed":
      return "bg-red-50 dark:bg-red-950";
    default:
      return "";
  }
}

function idPrefix(id: string): string {
  return id.slice(0, 8);
}

// ──────────────────────────────────────────────────────────────
// ──────────────────────────────────────────────────────────────

export function ExecutionComparisonView({ executionA, executionB }: ExecutionComparisonViewProps) {
  const t = useTranslations("solve.comparison");
  const resultA = executionA.result_data as OptimizationResult | undefined;
  const resultB = executionB.result_data as OptimizationResult | undefined;

  const objA = executionA.objective_value ?? resultA?.objective_value;
  const objB = executionB.objective_value ?? resultB?.objective_value;
  const objDelta = objA != null && objB != null ? objB - objA : null;

  const objectiveSense =
    (executionA.input_data?.objective as { sense?: string } | undefined)?.sense ??
    (executionB.input_data?.objective as { sense?: string } | undefined)?.sense;

  const compared = buildComparedVariables(executionA, executionB);
  const changedCount = compared.filter((v) => v.changeType !== "same").length;

  const timeDelta =
    executionA.execution_time_ms != null && executionB.execution_time_ms != null
      ? executionB.execution_time_ms - executionA.execution_time_ms
      : null;

  const creditsDelta = executionB.credits_consumed - executionA.credits_consumed;

  const objDeltaFormatted =
    objDelta != null ? formatObjDelta(objDelta, objectiveSense) : null;

  return (
    <div className="space-y-6">
      {/* ── Summary Header ── */}
      <div className="bg-card border border-border rounded-lg p-5">
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mb-4">
          {t("summary")}
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <div className="text-xs text-muted-foreground mb-1">{t("originRunA")}</div>
            <OriginBadge
              origin={executionA.origin}
              triggerName={executionA.input_data?.trigger_name as string | undefined}
            />
          </div>
          <div>
            <div className="text-xs text-muted-foreground mb-1">{t("originRunB")}</div>
            <OriginBadge
              origin={executionB.origin}
              triggerName={executionB.input_data?.trigger_name as string | undefined}
            />
          </div>

          <div>
            <div className="text-xs text-muted-foreground mb-1">{t("objectiveDelta")}</div>
            {objDeltaFormatted ? (
              <div className={`text-lg font-bold ${objDeltaFormatted.color}`}>
                {objDeltaFormatted.text}
              </div>
            ) : (
              <div className="text-lg font-bold text-muted-foreground">—</div>
            )}
          </div>

          <div>
            <div className="text-xs text-muted-foreground mb-1">{t("variablesChanged")}</div>
            <div className={`text-lg font-bold ${changedCount > 0 ? "text-yellow-600 dark:text-yellow-400" : "text-muted-foreground"}`}>
              {changedCount}
            </div>
          </div>

          <div>
            <div className="text-xs text-muted-foreground mb-1">{t("timeDifference")}</div>
            {timeDelta != null ? (
              <div className={`text-lg font-bold ${timeDelta > 0 ? "text-red-600 dark:text-red-400" : timeDelta < 0 ? "text-green-600 dark:text-green-400" : "text-muted-foreground"}`}>
                {formatMs(timeDelta)}
              </div>
            ) : (
              <div className="text-lg font-bold text-muted-foreground">—</div>
            )}
          </div>

          <div>
            <div className="text-xs text-muted-foreground mb-1">{t("creditsDifference")}</div>
            <div className={`text-lg font-bold ${creditsDelta > 0 ? "text-red-600 dark:text-red-400" : creditsDelta < 0 ? "text-green-600 dark:text-green-400" : "text-muted-foreground"}`}>
              {creditsDelta >= 0 ? "+" : ""}
              {creditsDelta}
            </div>
          </div>
        </div>
      </div>

      {/* ── Split-Pane Comparison Table ── */}
      <div className="bg-card border border-border rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/40">
                <th className="text-left px-4 py-3 font-medium text-muted-foreground w-1/3">
                  {t("variableName")}
                </th>
                <th className="text-left px-4 py-3 font-medium text-muted-foreground">
                  {t("type")}
                </th>
                <th className="text-right px-4 py-3 font-medium text-muted-foreground">
                  <div>{t("runA")}</div>
                  <div className="text-xs font-normal text-muted-foreground/70">
                    {idPrefix(executionA.id)} · {new Date(executionA.created_at).toLocaleDateString()}
                  </div>
                </th>
                <th className="text-right px-4 py-3 font-medium text-muted-foreground">
                  <div>{t("runB")}</div>
                  <div className="text-xs font-normal text-muted-foreground/70">
                    {idPrefix(executionB.id)} · {new Date(executionB.created_at).toLocaleDateString()}
                  </div>
                </th>
                <th className="text-right px-4 py-3 font-medium text-muted-foreground">
                  {t("delta")}
                </th>
              </tr>
            </thead>
            <tbody>
              {compared.length === 0 ? (
                <tr>
                  <td
                    colSpan={5}
                    className="px-4 py-8 text-center text-muted-foreground text-sm"
                  >
                    {t("noVariables")}
                  </td>
                </tr>
              ) : (
                compared.map((row) => (
                  <tr
                    key={row.name}
                    className={`border-b border-border last:border-0 ${rowBgClass(row.changeType)}`}
                  >
                    <td className="px-4 py-2 font-mono text-xs font-medium">{row.name}</td>
                    <td className="px-4 py-2 text-muted-foreground capitalize">{row.type}</td>
                    <td className="px-4 py-2 text-right font-mono text-xs">
                      {formatValue(row.valueA)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs">
                      {formatValue(row.valueB)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs">
                      {row.delta != null && row.changeType === "changed" ? (
                        <span className="text-yellow-700 dark:text-yellow-300 font-semibold">
                          {formatDelta(row.delta)}
                        </span>
                      ) : row.changeType === "added" ? (
                        <span className="text-green-700 dark:text-green-300 text-xs">{t("added")}</span>
                      ) : row.changeType === "removed" ? (
                        <span className="text-red-700 dark:text-red-300 text-xs">{t("removed")}</span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Legend ── */}
      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-sm bg-yellow-100 dark:bg-yellow-900 border border-yellow-300" />
          {t("legend.changed")}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-sm bg-green-100 dark:bg-green-900 border border-green-300" />
          {t("legend.addedInB")}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-3 rounded-sm bg-red-100 dark:bg-red-900 border border-red-300" />
          {t("legend.removedInA")}
        </span>
      </div>
    </div>
  );
}
