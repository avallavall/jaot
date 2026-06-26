"use client";

import { useState, useEffect, useMemo, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, ModelExecution } from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";
import { OptimizationResult } from "@/lib/types";
import type { InfeasibilityAnalysis } from "@/lib/llm-types";
import { extractProgressHistory, extractObjectiveSense } from "@/lib/result-utils";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { SolutionExplorerTable } from "@/components/solve/SolutionExplorerTable";
import { VariableValuesChart } from "@/components/solve/VariableValuesChart";
import { InsightsPanel } from "@/components/solve/InsightsPanel";
import { ExportButtons } from "@/components/solve/ExportButtons";
import { SensitivityTab } from "@/components/solve/SensitivityTab";
import { SolutionExplainer } from "@/components/solve/SolutionExplainer";
import { InfeasibilityPanel } from "@/components/solve/InfeasibilityPanel";
import { OriginBadge } from "@/components/solve/OriginBadge";
import { GapConvergenceChart } from "@/components/solve/GapConvergenceChart";
import { useTranslations } from "next-intl";
import { RotateCcw } from "lucide-react";

export default function ExecutionDetailPage() {
  const t = useTranslations("solve.execution");
  const params = useParams();
  const router = useRouter();
  const executionId = params.executionId as string;
  const chartRef = useRef<HTMLDivElement>(null);

  const [execution, setExecution] = useState<ModelExecution | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const resultData = execution?.result_data as OptimizationResult | undefined;
  const variables = resultData?.variables ?? [];
  const isInfeasible = execution?.solver_status === "infeasible";
  // infeasibility_analysis is an additive result_data field (P2); read it loosely so
  // a revisit shows the cached conflict immediately without depending on regen drift.
  const infeasibilityAnalysis =
    (resultData as { infeasibility_analysis?: InfeasibilityAnalysis | null } | undefined)
      ?.infeasibility_analysis ?? null;
  const progressHistory = useMemo(
    () => extractProgressHistory(resultData as Record<string, unknown> | undefined),
    [resultData],
  );
  const objectiveSense = useMemo(
    () => extractObjectiveSense(execution?.input_data),
    [execution?.input_data],
  );

  useEffect(() => {
    loadExecution();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [executionId]);

  const loadExecution = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getExecution(executionId);
      setExecution(data);
    } catch (err) {
      setError(getErrorMessage(err, t("failedToLoad")));
    } finally {
      setLoading(false);
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "completed":
        return "bg-green-100 text-green-800 border-green-200";
      case "failed":
        return "bg-red-100 text-red-800 border-red-200";
      case "running":
        return "bg-blue-100 text-blue-800 border-blue-200";
      case "timeout":
        return "bg-yellow-100 text-yellow-800 border-yellow-200";
      default:
        return "bg-gray-100 text-gray-800 border-gray-200";
    }
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString();
  };

  const formatJson = (obj: unknown) => {
    return JSON.stringify(obj, null, 2);
  };

  if (loading) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-muted rounded w-1/3"></div>
          <div className="h-64 bg-muted rounded"></div>
        </div>
      </div>
    );
  }

  if (error || !execution) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-6 text-center">
          <p className="text-destructive mb-4">{error || t("executionNotFound")}</p>
          <Button onClick={() => router.back()}>{t("goBack")}</Button>
        </div>
      </div>
    );
  }

  // Show "Use as warm start" only for completed optimal/feasible executions
  const canUseAsWarmStart =
    execution.status === "completed" &&
    (execution.solver_status === "optimal" || execution.solver_status === "feasible");

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="mb-6">
        <button
          onClick={() => router.back()}
          className="text-sm text-muted-foreground hover:text-foreground mb-2 inline-block"
        >
          {t("back")}
        </button>
        <div className="flex items-center gap-4 flex-wrap">
          <h1 className="text-2xl font-bold text-foreground">{t("title")}</h1>
          <span
            className={`px-3 py-1 rounded-full text-sm font-medium border ${getStatusColor(execution.status)}`}
          >
            {execution.status}
          </span>
          <OriginBadge
            origin={execution.origin}
            triggerName={execution.input_data?.trigger_name as string | undefined}
          />
          {execution.trigger_id && (
            <button
              onClick={() => router.push(`/triggers/${execution.trigger_id}`)}
              className="text-sm text-primary hover:underline"
            >
              {t("viewTriggerConfig")}
            </button>
          )}
        </div>
        <p className="text-muted-foreground text-sm mt-1">{t("id", { id: execution.id })}</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-card border border-border rounded-lg p-4">
          <div className="text-sm text-muted-foreground">{t("started")}</div>
          <div className="font-medium">{formatDate(execution.created_at)}</div>
        </div>
        <div className="bg-card border border-border rounded-lg p-4">
          <div className="text-sm text-muted-foreground">{t("duration")}</div>
          <div className="font-medium">
            {execution.execution_time_ms ? `${execution.execution_time_ms}ms` : "-"}
          </div>
        </div>
        <div className="bg-card border border-border rounded-lg p-4">
          <div className="text-sm text-muted-foreground">{t("creditsUsed")}</div>
          <div className="font-medium">{execution.credits_consumed}</div>
        </div>
        <div className="bg-card border border-border rounded-lg p-4">
          <div className="text-sm text-muted-foreground">{t("solverStatus")}</div>
          <div className="font-medium">{execution.solver_status || "-"}</div>
        </div>
        <div className="bg-card border border-border rounded-lg p-4">
          <div className="text-sm text-muted-foreground">{t("solver")}</div>
          <div className="font-medium">
            {execution.solver_name
              ? execution.solver_name.toUpperCase()
              : "SCIP"}
          </div>
        </div>
      </div>

      {execution.error_message && (
        <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-4 mb-6">
          <h3 className="font-semibold text-destructive mb-2">{t("error")}</h3>
          <pre className="text-sm text-destructive whitespace-pre-wrap">
            {execution.error_message}
          </pre>
        </div>
      )}

      {execution.objective_value != null && (
        <div className="mb-6 p-5 bg-primary/10 rounded-lg border border-primary/20">
          <div className="text-sm text-muted-foreground mb-1">{t("objectiveValue")}</div>
          <div className="text-2xl font-bold text-primary">
            {execution.objective_value.toLocaleString(undefined, { maximumFractionDigits: 4 })}
          </div>
        </div>
      )}

      {/* Results Tabs: Solution Explorer + Sensitivity */}
      <div className="mb-8">
        <Tabs defaultValue="results">
          <TabsList className="mb-4">
            <TabsTrigger value="results">{t("results")}</TabsTrigger>
            <TabsTrigger value="visualization">{t("visualization")}</TabsTrigger>
            <TabsTrigger value="sensitivity">{t("sensitivity")}</TabsTrigger>
          </TabsList>

          <TabsContent value="results">
            {variables.length > 0 && (
              <div className="mb-6">
                <SolutionExplainer executionId={executionId} canExplain={canUseAsWarmStart} />
              </div>
            )}

            {isInfeasible && (
              <div className="mb-6">
                <InfeasibilityPanel
                  executionId={executionId}
                  initialAnalysis={infeasibilityAnalysis}
                />
              </div>
            )}

            {variables.length > 0 && (
              <div className="mb-8">
                <h2 className="text-lg font-semibold text-foreground mb-3">{t("solutionExplorer")}</h2>
                <SolutionExplorerTable
                  variables={variables}
                  sensitivity={resultData?.sensitivity ?? undefined}
                />
              </div>
            )}

            {/* Convergence chart — uses real progress history captured by the
                SCIP event handler. Falls back to a single-point chart if the
                solver only reported the final solution. */}
            {progressHistory.length > 0 && (
              <div className="mt-6">
                <h2 className="text-lg font-semibold text-foreground mb-3">
                  {t("gapConvergence")}
                </h2>
                <div className="bg-card border border-border rounded-lg p-4" ref={chartRef}>
                  <GapConvergenceChart
                    progressHistory={progressHistory}
                    objectiveSense={objectiveSense}
                  />
                </div>
              </div>
            )}

            {progressHistory.length === 0 && resultData?.gap != null && (
              <div className="mt-4 p-4 bg-card border border-border rounded-lg">
                <span className="text-sm text-muted-foreground">{t("gapConvergence")}: </span>
                <span className="text-sm font-medium">{(resultData.gap * 100).toFixed(4)}%</span>
              </div>
            )}
          </TabsContent>

          <TabsContent value="visualization">
            {variables.length > 0 && (
              <div className="mb-6">
                <h2 className="text-lg font-semibold text-foreground mb-3">{t("variableValues")}</h2>
                <div className="bg-card border border-border rounded-lg p-4">
                  <VariableValuesChart variables={variables} />
                </div>
              </div>
            )}
            <div>
              <h2 className="text-lg font-semibold text-foreground mb-3">{t("insightsTitle")}</h2>
              <div className="bg-card border border-border rounded-lg p-4">
                <InsightsPanel executionId={executionId} />
              </div>
            </div>
          </TabsContent>

          <TabsContent value="sensitivity">
            <SensitivityTab sensitivity={resultData?.sensitivity} />
          </TabsContent>
        </Tabs>
      </div>

      <div className="space-y-3 mb-8">
        <details className="bg-card border border-border rounded-lg overflow-hidden">
          <summary className="px-4 py-3 text-sm font-medium cursor-pointer hover:bg-muted/30 transition-colors select-none">
            {t("inputDataRawJson")}
          </summary>
          <div className="border-t border-border">
            <pre className="bg-muted/40 p-4 text-xs overflow-auto max-h-64 font-mono">
              {formatJson(execution.input_data)}
            </pre>
          </div>
        </details>

        {execution.result_data && (
          <details className="bg-card border border-border rounded-lg overflow-hidden">
            <summary className="px-4 py-3 text-sm font-medium cursor-pointer hover:bg-muted/30 transition-colors select-none">
              {t("resultDataRawJson")}
            </summary>
            <div className="border-t border-border">
              <pre className="bg-muted/40 p-4 text-xs overflow-auto max-h-64 font-mono">
                {formatJson(execution.result_data)}
              </pre>
            </div>
          </details>
        )}
      </div>

      <div className="flex flex-wrap gap-3">
        {execution.organization_model_id ? (
          <>
            <Button
              variant="outline"
              onClick={() => router.push(`/solve/${execution.organization_model_id}`)}
            >
              {t("runAgain")}
            </Button>
            {canUseAsWarmStart && (
              <Button
                variant="outline"
                onClick={() =>
                  router.push(
                    `/solve/${execution.organization_model_id}?warm_start_id=${execution.id}`
                  )
                }
              >
                <RotateCcw className="w-4 h-4 mr-2" />
                {t("useAsWarmStart")}
              </Button>
            )}
            <Button
              variant="outline"
              onClick={() => router.push(`/solve/${execution.organization_model_id}/history`)}
            >
              {t("viewAllExecutions")}
            </Button>
          </>
        ) : (
          <p className="text-sm text-muted-foreground py-1">
            {t("externalExecution")}
          </p>
        )}
        <ExportButtons execution={execution} chartRef={chartRef} />
      </div>
    </div>
  );
}
