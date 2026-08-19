"use client";

import { useState, useEffect, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, ModelExecution } from "@/lib/api";
import { translateApiError } from "@/lib/errors";
import { OptimizationResult } from "@/lib/types";
import type { InfeasibilityAnalysis } from "@/lib/llm-types";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { StructuredSolutionView } from "@/components/solve/StructuredSolutionView";
import { ExactAnalysisPanel } from "@/components/solve/ExactAnalysisPanel";
import { VariableValuesChart } from "@/components/solve/VariableValuesChart";
import { InsightsPanel } from "@/components/solve/InsightsPanel";
import { ExportButtons } from "@/components/solve/ExportButtons";
import { SensitivityTab } from "@/components/solve/SensitivityTab";
import { ScenarioAnalysisSection } from "@/components/solve/ScenarioAnalysisSection";
import { SolutionExplainer } from "@/components/solve/SolutionExplainer";
import { InfeasibilityPanel } from "@/components/solve/InfeasibilityPanel";
import { OriginBadge } from "@/components/solve/OriginBadge";
import { noModelMessageKey } from "@/lib/execution-origin";
import { readVariableBounds } from "@/lib/variable-bounds";
import { SolveFactCard } from "@/components/solve/SolveFactCard";
import { useSolverCapabilities } from "@/hooks/useSolvers";
import { solverDisplayName } from "@/lib/solver-display";
import { useTranslations } from "next-intl";
import { useCommonLabels } from "@/hooks/useCommonLabels";
import { useDateFormat } from "@/hooks/useDateFormat";
import { Database } from "lucide-react";

/** How often an unfinished run is re-fetched while its detail page is open. */
const EXECUTION_POLL_MS = 3000;

export default function ExecutionDetailPage() {
  const t = useTranslations("solve.execution");
  const tError = useTranslations("errors.codes");
  const { dayTime } = useDateFormat();
  const { statusLabel } = useCommonLabels();
  const params = useParams();
  const router = useRouter();
  const executionId = params.executionId as string;
  const chartRef = useRef<HTMLDivElement>(null);

  const [execution, setExecution] = useState<ModelExecution | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const resultData = execution?.result_data as OptimizationResult | undefined;
  const variables = resultData?.variables ?? [];
  // The range each variable was declared with. It is in the problem the run
  // stored, which this page already holds — four columns of the Solution
  // Explorer were placeholders for want of passing it down.
  const variableBounds = readVariableBounds(execution?.input_data);
  const isInfeasible = execution?.solver_status === "infeasible";
  // infeasibility_analysis is an additive result_data field (P2); read it loosely so
  // a revisit shows the cached conflict immediately without depending on regen drift.
  const infeasibilityAnalysis =
    (resultData as { infeasibility_analysis?: InfeasibilityAnalysis | null } | undefined)
      ?.infeasibility_analysis ?? null;
  // The solver that ACTUALLY ran: under solver_name="auto" the backend routes,
  // and `solver_used` is the only field that records where it landed. Its
  // capabilities are what the analysis panels may promise for this run.
  const effectiveSolver = resultData?.solver_used ?? execution?.solver_name ?? null;
  const solverCapabilities = useSolverCapabilities(effectiveSolver);
  useEffect(() => {
    loadExecution();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [executionId]);

  // Arriving here with the run still in flight is a normal path — it is exactly what
  // the list's "View" button offers on a pending row. Poll until it settles instead
  // of freezing on "pending" until the user thinks to refresh by hand.
  useEffect(() => {
    const status = execution?.status;
    if (status !== "pending" && status !== "running") return;
    const timer = setInterval(() => {
      void loadExecution({ silent: true });
    }, EXECUTION_POLL_MS);
    return () => clearInterval(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [execution?.status, executionId]);

  // `silent` refreshes keep the rendered run on screen: no skeleton flash, and a
  // transient poll failure does not replace a perfectly good page with an error.
  const loadExecution = async ({ silent = false }: { silent?: boolean } = {}) => {
    if (!silent) {
      setLoading(true);
      setError(null);
    }
    try {
      const data = await api.getExecution(executionId);
      setExecution(data);
    } catch (err) {
      // The server's `detail` is English by contract ("Execution not found",
      // which is what this page used to print inside a Spanish page). Render
      // the code it names, and the translated fallback when there is none.
      if (!silent) setError(translateApiError(err, tError, t("failedToLoad")));
    } finally {
      if (!silent) setLoading(false);
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
      case "pending":
        return "bg-yellow-100 text-yellow-800 border-yellow-200";
      case "timeout":
        return "bg-yellow-100 text-yellow-800 border-yellow-200";
      default:
        return "bg-gray-100 text-gray-800 border-gray-200";
    }
  };

  const formatDate = (dateStr: string) => dayTime(dateStr);

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

  // Explain any completed run that actually produced a solution.
  //
  // A run stopped by its time limit still holds one whenever the solver found an
  // incumbent: the adapters leave objective_value unset when they did not (see
  // cbc.py, which reports only dual_bound in that case). Requiring optimal or
  // feasible withheld the explanation from a perfectly usable answer whose only
  // shortcoming is that the solver ran out of time to prove it was the best.
  const canExplain =
    execution.status === "completed" &&
    (execution.solver_status === "optimal" ||
      execution.solver_status === "feasible" ||
      (execution.solver_status === "time_limit" && execution.objective_value != null));

  // P1.5 fusion: the run's model is a ModelProject; historic rows carry the
  // legacy org-model id, which the backfill preserved as the project id.
  const projectId = execution.model_project_id ?? execution.organization_model_id;

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
            {statusLabel(execution.status)}
          </span>
          <OriginBadge
            origin={execution.origin}
            sourceKind={execution.source_kind ?? undefined}
            triggerName={execution.input_data?.trigger_name as string | undefined}
          />
          {/* §8/S1: which dataset (scenario) the run was compiled against. */}
          {execution.dataset_name && (
            <span
              data-testid="execution-dataset-badge"
              title={t("datasetBadge")}
              className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-sm text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200"
            >
              <Database className="h-3.5 w-3.5" />
              {execution.dataset_name}
            </span>
          )}
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
          <div className="text-sm text-muted-foreground">{t("solverStatus")}</div>
          <div className="font-medium">{execution.solver_status || "-"}</div>
        </div>
        <div className="bg-card border border-border rounded-lg p-4">
          <div className="text-sm text-muted-foreground">{t("solver")}</div>
          <div className="font-medium">
            {/* Prefer the solver that actually ran (auto-routing resolves to it)
                over the one that was requested, and render the brand casing
                rather than a blunt uppercase. */}
            {effectiveSolver ? solverDisplayName(effectiveSolver) : "SCIP"}
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
            <TabsTrigger value="results" data-testid="execution-tab-results">
              {t("results")}
            </TabsTrigger>
            <TabsTrigger value="visualization" data-testid="execution-tab-visualization">
              {t("visualization")}
            </TabsTrigger>
            <TabsTrigger value="sensitivity" data-testid="execution-tab-sensitivity">
              {t("sensitivity")}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="results">
            {variables.length > 0 && (
              <div className="mb-6">
                <SolutionExplainer
                  executionId={executionId}
                  canExplain={canExplain}
                  hasSensitivity={Boolean(resultData?.sensitivity)}
                />
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
                <StructuredSolutionView variables={variables} bounds={variableBounds} />
              </div>
            )}

            {/* Honest post-solve summary (A2). The old live convergence chart was
                a flat, useless line for essentially every real model (SCIP proves
                optimality node-by-node while the incumbent barely moves), so we
                state how the model solved instead of drawing a fake curve. */}
            {resultData && !isInfeasible && (
              <div className="mt-6" ref={chartRef}>
                <h2 className="text-lg font-semibold text-foreground mb-3">{t("solveSummary")}</h2>
                <SolveFactCard
                  status={execution?.solver_status}
                  objectiveValue={resultData.objective_value ?? execution?.objective_value}
                  gap={resultData.gap}
                  nodes={resultData.nodes}
                  iterations={resultData.iterations}
                  solveTimeSeconds={resultData.solve_time_seconds}
                />
              </div>
            )}

            {/* Exact, solution-based analysis (A3): binding constraints, slack/
                utilization and objective contributions computed from x*. Anything
                that answers "what if it changed?" belongs to the Sensitivity tab. */}
            {resultData && !isInfeasible && variables.length > 0 && (
              <div className="mt-8">
                <h2 className="text-lg font-semibold text-foreground mb-3">{t("analysisTitle")}</h2>
                <ExactAnalysisPanel executionId={executionId} />
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
            {/* The what-if by re-solves (L2) leads: it is the honest answer to
                the question the LP-relaxation duals below only approximate, and
                it belongs in the tab that carries the name. It used to sit at
                the bottom of Results, where nobody looking for sensitivity went. */}
            {resultData && !isInfeasible && variables.length > 0 && (
              <div className="mb-8">
                <ScenarioAnalysisSection executionId={executionId} />
              </div>
            )}
            <SensitivityTab
              sensitivity={resultData?.sensitivity}
              solverName={effectiveSolver}
              capabilities={solverCapabilities}
              solverStatus={execution.solver_status}
            />
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
        {projectId ? (
          // This button opens the studio's Solve tab and nothing else. It was
          // labelled "Run Again", which is what it looks like it should do and
          // what a reader assumed it had done: pressing it left the execution
          // count exactly where it was. Re-running belongs on the Solve tab,
          // where the solver and the limits are chosen — so the button now says
          // where it goes instead of promising work it does not do.
          <Button
            variant="outline"
            onClick={() => router.push(`/studio/${projectId}/solve`)}
          >
            {t("openInStudio")}
          </Button>
        ) : (
          // "Triggered externally" was said about a file imported through this
          // app two seconds earlier — the record itself says origin="import",
          // source_kind="imported_file". What is true of every one of these is
          // that no saved model is behind it, so name that instead of inventing
          // a story about where it came from.
          <p className="text-sm text-muted-foreground py-1" data-testid="execution-no-model">
            {t(noModelMessageKey(execution.source_kind))}
          </p>
        )}
        <ExportButtons execution={execution} chartRef={chartRef} />
      </div>
    </div>
  );
}
