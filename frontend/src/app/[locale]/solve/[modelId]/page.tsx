"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { api, OrganizationModel, ModelExecution, InputField } from "@/lib/api";
import { getErrorMessage, getErrorStatus } from "@/lib/errors";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ExecutionProgress } from "@/components/ExecutionProgress";
import { SolverSelect } from "@/components/solve/SolverSelect";
import { WarmStartDropdown, WarmStartCandidateInfo } from "@/components/solve/WarmStartDropdown";
import { useSolvers } from "@/hooks/useSolvers";
import { HelpTooltip } from "@/components/ui/help-tooltip";
import { useTranslations } from "next-intl";
import { useCommonLabels } from "@/hooks/useCommonLabels";
import { Play, Loader2, Clock, Upload, Zap } from "lucide-react";

export default function RunModelPage() {
  const t = useTranslations("solve.model");
  const { categoryLabel } = useCommonLabels();
  const tHelp = useTranslations("solve.helpTooltips");
  const tWarm = useTranslations("solve.warmStart");

  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const modelId = params.modelId as string;
  const isRerun = searchParams.get("rerun") === "true";

  const [model, setModel] = useState<OrganizationModel | null>(null);
  const [schema, setSchema] = useState<{
    input_fields: InputField[];
    example_input: Record<string, unknown>;
  } | null>(null);
  const [inputJson, setInputJson] = useState("");
  const [loading, setLoading] = useState(true);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState<ModelExecution | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asyncExecutionId, setAsyncExecutionId] = useState<string | null>(null);
  const [useAsyncMode, setUseAsyncMode] = useState(false);
  // Live credit estimate for the run button. null = unknown (invalid/partial
  // input or estimate in flight) → button shows just the mode label.
  const [estimatedCredits, setEstimatedCredits] = useState<number | null>(null);
  const [selectedWarmStartId, setSelectedWarmStartId] = useState<string | null>(null);
  const [selectedWarmStartInfo, setSelectedWarmStartInfo] = useState<WarmStartCandidateInfo | null>(null);
  const [warmStartRefreshKey, setWarmStartRefreshKey] = useState(0);
  const { solverName, setSolverName, availableSolvers, solversLoading } = useSolvers();

  // Read warm_start_id from URL search params on mount to pre-select the dropdown
  useEffect(() => {
    const warmStartId = searchParams.get("warm_start_id");
    if (warmStartId) {
      setSelectedWarmStartId(warmStartId);
    }
  }, [searchParams]);

  const handleWarmStartSelect = (
    executionId: string | null,
    info?: WarmStartCandidateInfo,
  ) => {
    setSelectedWarmStartId(executionId);
    setSelectedWarmStartInfo(executionId ? (info ?? null) : null);
  };

  useEffect(() => {
    loadModel();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelId]);

  const loadModel = async () => {
    setLoading(true);
    setError(null);
    try {
      const [modelData, schemaData] = await Promise.all([
        api.getMyModel(modelId),
        api.getMyModelSchema(modelId),
      ]);
      setModel(modelData);
      setSchema(schemaData);

      // Check for rerun input from sessionStorage
      if (isRerun) {
        const rerunInput = sessionStorage.getItem(`rerun_input_${modelId}`);
        if (rerunInput) {
          setInputJson(rerunInput);
          sessionStorage.removeItem(`rerun_input_${modelId}`);
          // Clear the URL param
          router.replace(`/solve/${modelId}`);
          return;
        }
      }

      setInputJson(JSON.stringify(schemaData.example_input, null, 2));
    } catch (err) {
      setError(getErrorMessage(err, t("failedToLoad")));
    } finally {
      setLoading(false);
    }
  };

  const hasExampleInput = schema?.example_input && Object.keys(schema.example_input).length > 0;

  const handleLoadExample = () => {
    if (hasExampleInput) {
      setInputJson(JSON.stringify(schema!.example_input, null, 2));
    }
  };

  // Validate input against schema
  const validateInput = (data: Record<string, unknown>): string[] => {
    const errors: string[] = [];
    if (!schema?.input_fields) return errors;

    for (const field of schema.input_fields) {
      const value = data[field.name];

      // Check required fields
      if (field.required && (value === undefined || value === null)) {
        errors.push(`Missing required field: ${field.label || field.name}`);
        continue;
      }

      if (value === undefined || value === null) continue;

      // Type validation
      if (field.type === 'number' || field.type === 'integer') {
        if (typeof value !== 'number') {
          errors.push(`${field.label || field.name} must be a number`);
        } else {
          if (field.minimum != null && value < field.minimum) {
            errors.push(`${field.label || field.name} must be >= ${field.minimum}`);
          }
          if (field.maximum != null && value > field.maximum) {
            errors.push(`${field.label || field.name} must be <= ${field.maximum}`);
          }
        }
      }

      if (field.type === 'string' && typeof value !== 'string') {
        errors.push(`${field.label || field.name} must be a string`);
      }

      if (field.type === 'array' && !Array.isArray(value)) {
        errors.push(`${field.label || field.name} must be an array`);
      }

      if (field.type === 'object' && (typeof value !== 'object' || Array.isArray(value))) {
        errors.push(`${field.label || field.name} must be an object`);
      }

      // Enum validation
      if (field.enum && !field.enum.includes(String(value))) {
        errors.push(`${field.label || field.name} must be one of: ${field.enum.join(', ')}`);
      }
    }

    return errors;
  };

  const handleExecute = async () => {
    setResult(null);
    setError(null);
    setAsyncExecutionId(null);

    let inputData: Record<string, unknown>;
    try {
      inputData = JSON.parse(inputJson);
    } catch {
      setError(t("invalidJsonSyntax"));
      return;
    }

    // Validate against schema
    const validationErrors = validateInput(inputData);
    if (validationErrors.length > 0) {
      setError(`Validation errors:\n• ${validationErrors.join('\n• ')}`);
      return;
    }

    // Include warm_start in the payload if selected
    if (selectedWarmStartId) {
      inputData = {
        ...inputData,
        warm_start: { execution_id: selectedWarmStartId },
      };
    }

    setExecuting(true);

    try {
      if (useAsyncMode) {
        // Async execution - get task ID and show progress
        const asyncResult = await api.executeModelAsync(modelId, inputData, solverName);
        // Use task_id for polling the async status endpoint
        setAsyncExecutionId(asyncResult.task_id);
        // Don't set executing to false - let the progress component handle it
      } else {
        // Sync execution
        const executionResult = await api.executeModel(modelId, inputData, solverName);
        setResult(executionResult);
        setExecuting(false);
        setWarmStartRefreshKey((k) => k + 1);
      }
    } catch (err) {
      const status = getErrorStatus(err);
      let msg: string;
      if (status === 402) {
        msg = t("insufficientCredits");
      } else if (status === 422) {
        msg = t("invalidInput", { detail: getErrorMessage(err, t("executionFailed")) });
      } else if (status === 408) {
        msg = t("solverTimeout");
      } else {
        msg = getErrorMessage(err, t("executionFailed"));
      }
      setError(msg);
      setExecuting(false);
    }
  };

  const handleAsyncComplete = (statusData: Record<string, unknown>) => {
    setExecuting(false);
    setAsyncExecutionId(null);

    const modelResult = statusData.result as Record<string, unknown> | undefined;
    const creditsUsed = statusData.credits_used as number;
    const executionTimeMs = statusData.execution_time_ms as number;

    setResult({
      id: (statusData.execution_id as string) || asyncExecutionId || '',
      status: 'completed',
      result_data: modelResult || {},
      credits_consumed: creditsUsed || 0,
      execution_time_ms: executionTimeMs,
    } as unknown as ModelExecution);
    setWarmStartRefreshKey((k) => k + 1);
  };

  const handleAsyncError = (errorMsg: string) => {
    setExecuting(false);
    setAsyncExecutionId(null);
    setError(errorMsg);
  };

  // Estimate the dynamic credit cost for the run button: render the problem
  // (preview) then price it (validate → estimated_credits). Debounced and
  // best-effort — any failure (invalid/partial JSON, render error) clears the
  // estimate so the button falls back to just the mode label.
  useEffect(() => {
    let cancelled = false;
    let inputData: Record<string, unknown>;
    try {
      inputData = JSON.parse(inputJson);
    } catch {
      setEstimatedCredits(null);
      return;
    }
    const handle = setTimeout(async () => {
      try {
        const problem = await api.previewModel(modelId, inputData);
        const validation = await api.validateProblem(problem);
        if (!cancelled) {
          setEstimatedCredits(
            typeof validation.estimated_credits === "number"
              ? validation.estimated_credits
              : null,
          );
        }
      } catch {
        if (!cancelled) setEstimatedCredits(null);
      }
    }, 500);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [inputJson, modelId]);

  if (loading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    );
  }

  if (!model) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="p-4 bg-destructive/10 text-destructive rounded-lg">
          {t("modelNotFound")}
        </div>
        <Button className="mt-4" onClick={() => router.push("/solve")}>
          {t("backToModels")}
        </Button>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8">
      <button
        onClick={() => router.push("/solve")}
        className="flex items-center gap-2 text-muted-foreground hover:text-foreground mb-6"
      >
        &larr; {t("backToModels")}
      </button>

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">{model.display_name}</h1>
          {model.description && (
            <p className="text-muted-foreground mt-1">{model.description}</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => router.push(`/solve/${modelId}/history`)}>
            <Clock className="w-4 h-4 mr-1.5" />
            {t("history")}
          </Button>
          <Button variant="outline" size="sm" onClick={() => router.push(`/solve/${modelId}/publish`)}>
            <Upload className="w-4 h-4 mr-1.5" />
            {model.catalog_id ? t("updateListing") : t("publish")}
          </Button>
        </div>
      </div>
      <div className="flex items-center justify-between mb-6">
        <div />
        <div className="text-right">
          {model.credits_per_execution > 0 ? (
            <div className="text-sm text-muted-foreground">
              {t("credits", { count: model.credits_per_execution })} {t("perExecution")}
            </div>
          ) : (
            <div className="inline-flex items-center gap-1 text-sm text-muted-foreground">
              {t("dynamicCredits")}
              <HelpTooltip content={t("dynamicCreditsTooltip")} side="left" size={14} />
            </div>
          )}
        </div>
      </div>

      {model.category && (
        <div className="flex flex-wrap gap-2 mb-6">
          <span className="px-3 py-1 text-sm bg-primary/10 text-primary rounded-full">
            {categoryLabel(model.category)}
          </span>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-card border rounded-lg p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">{t("inputData")}</h2>
            {hasExampleInput && (
              <Button variant="outline" size="sm" onClick={handleLoadExample}>
                {t("loadExample")}
              </Button>
            )}
          </div>

          <p className="text-sm text-muted-foreground mb-4">
            {t("enterJsonDescription")}
          </p>

          <Textarea
            value={inputJson}
            onChange={(e) => setInputJson(e.target.value)}
            className="font-mono text-sm min-h-[300px] mb-4"
            placeholder='{"key": "value"}'
          />

          <div className="flex items-center gap-3 mb-4 p-3 bg-muted/50 rounded-lg">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={useAsyncMode}
                onChange={(e) => setUseAsyncMode(e.target.checked)}
                className="w-4 h-4 rounded border-gray-300"
              />
              <span className="text-sm font-medium">{t("asyncMode")}</span>
            </label>
            <span className="text-xs text-muted-foreground">
              {useAsyncMode
                ? t("asyncDescription")
                : t("syncDescription")}
            </span>
          </div>

          <div className={`mb-4 p-3 rounded-lg border ${
            selectedWarmStartId
              ? "bg-primary/5 border-primary/30"
              : "bg-muted/30 border-border"
          }`}>
            <div className="flex items-center gap-2 mb-2">
              {selectedWarmStartId && (
                <Zap className="w-4 h-4 text-primary" />
              )}
              <label className="text-sm font-medium text-foreground">
                {t("warmStart")}
              </label>
              <HelpTooltip content={tHelp("warmStart")} side="right" size={14} />
              {!selectedWarmStartId && (
                <span className="text-xs text-muted-foreground">
                  {t("warmStartHint")}
                </span>
              )}
              {selectedWarmStartId && (
                <span className="ml-auto text-xs font-medium text-primary">
                  {tWarm("activeLabel")}
                </span>
              )}
            </div>
            <WarmStartDropdown
              modelId={modelId}
              onSelect={handleWarmStartSelect}
              selectedId={selectedWarmStartId}
              refreshKey={warmStartRefreshKey}
            />
            {selectedWarmStartId && selectedWarmStartInfo && (
              <div className="mt-2 flex items-center gap-3 text-xs">
                <span className="text-primary font-medium">
                  {tWarm("creditDiscount")}
                </span>
                {selectedWarmStartInfo.variable_count > 0 && (
                  <span className="text-muted-foreground">
                    {tWarm("variables", { count: selectedWarmStartInfo.variable_count })}
                  </span>
                )}
              </div>
            )}
          </div>

          <SolverSelect
            solverName={solverName}
            onSolverChange={setSolverName}
            availableSolvers={availableSolvers}
            loading={solversLoading}
          />

          <Button
            className="w-full"
            size="lg"
            onClick={handleExecute}
            disabled={executing}
          >
            {executing ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                {useAsyncMode ? t("starting") : t("solving")}
              </>
            ) : (
              <>
                <Play className="w-4 h-4 mr-2" />
                {t("runModel", {
                  mode: useAsyncMode ? t("modeAsync") : t("modeSync"),
                  credits: estimatedCredits ?? 0,
                })}
              </>
            )}
          </Button>
        </div>

        <div className="bg-card border rounded-lg p-6">
          <h2 className="text-lg font-semibold mb-4">{t("result")}</h2>

          {asyncExecutionId && (
            <ExecutionProgress
              executionId={asyncExecutionId}
              onComplete={handleAsyncComplete}
              onError={handleAsyncError}
              showConvergenceGraph={true}
            />
          )}

          {!result && !error && !asyncExecutionId && (
            <div className="text-center py-16 text-muted-foreground">
              <div className="text-4xl mb-4">📊</div>
              <p>{t("runToSeeResults")}</p>
            </div>
          )}

          {error && (
            <div className="p-4 bg-destructive/10 text-destructive rounded-lg">
              {error}
            </div>
          )}

          {result && (
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <span
                  className={`px-3 py-1 rounded-full text-sm font-medium ${
                    result.status === "completed"
                      ? "bg-green-100 text-green-800"
                      : result.status === "failed"
                      ? "bg-red-100 text-red-800"
                      : "bg-yellow-100 text-yellow-800"
                  }`}
                >
                  {result.status.toUpperCase()}
                </span>
                {result.solver_status && (
                  <span className="text-sm text-muted-foreground">
                    ({result.solver_status})
                  </span>
                )}
              </div>

              {result.status === "completed" && result.result_data && (
                <>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="bg-muted/50 rounded-lg p-4">
                      <div className="text-sm text-muted-foreground">{t("objectiveValue")}</div>
                      <div className="text-2xl font-bold">
                        {result.result_data.objective_value?.toFixed(4) || "N/A"}
                      </div>
                    </div>
                    <div className="bg-muted/50 rounded-lg p-4">
                      <div className="text-sm text-muted-foreground">{t("solveTime")}</div>
                      <div className="text-2xl font-bold">
                        {result.result_data.solve_time_seconds?.toFixed(3)}s
                      </div>
                    </div>
                  </div>

                  {(result.result_data as unknown as Record<string, unknown>)?.model && (
                    <div>
                      <h3 className="font-medium mb-2">{t("modelLabel")}</h3>
                      <div className="bg-muted rounded-lg p-4 max-h-64 overflow-y-auto">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="border-b">
                              <th className="text-left py-2">{t("variable")}</th>
                              <th className="text-right py-2">{t("value")}</th>
                            </tr>
                          </thead>
                          <tbody>
                            {Object.entries((result.result_data as unknown as Record<string, unknown>).model as Record<string, unknown>).map(([name, value]) => (
                              <tr key={name} className="border-b last:border-0">
                                <td className="py-2 font-mono">{name}</td>
                                <td className="py-2 text-right font-mono">
                                  {typeof value === "number" ? value.toFixed(4) : String(value)}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </>
              )}

              {result.error_message && (
                <div className="p-4 bg-destructive/10 text-destructive rounded-lg text-sm">
                  {result.error_message}
                </div>
              )}

              <div className="pt-4 border-t text-sm text-muted-foreground">
                {t("creditsConsumed", { credits: result.credits_consumed })}
                {result.execution_time_ms && (
                  <span className="ml-4">
                    {t("executionTime", { time: result.execution_time_ms })}
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {schema?.input_fields && schema.input_fields.length > 0 && (
        <div className="mt-8 bg-card border rounded-lg p-6">
          <h2 className="text-lg font-semibold mb-4">{t("inputParametersReference")}</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {schema.input_fields.map((field) => (
              <div key={field.name} className="p-3 bg-muted/50 rounded-lg">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium">{field.label || field.name}</span>
                  <span className="text-xs px-2 py-0.5 bg-background rounded">
                    {field.type}
                  </span>
                  {field.required && (
                    <span className="text-xs text-destructive">*</span>
                  )}
                </div>
                {field.description && (
                  <p className="text-xs text-muted-foreground">{field.description}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
