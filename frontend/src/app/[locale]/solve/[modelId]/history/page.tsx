"use client";

import { useState, useEffect, useMemo } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api, ModelExecution, OrganizationModel } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { useTranslations } from "next-intl";
import { useCommonLabels } from "@/hooks/useCommonLabels";
import { Copy, Play } from "lucide-react";
import ObjectiveTrendChart from "@/components/solve/ObjectiveTrendChart";
import { OriginBadge } from "@/components/solve/OriginBadge";

export default function ModelHistoryPage() {
  const t = useTranslations("solve.history");
  const { statusLabel } = useCommonLabels();
  const params = useParams();
  const router = useRouter();
  const modelId = params.modelId as string;

  const [model, setModel] = useState<OrganizationModel | null>(null);
  const [executions, setExecutions] = useState<ModelExecution[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [originFilter, setOriginFilter] = useState<string>("");

  // Comparison selection state — at most 2 executions can be selected
  const [selectedForCompare, setSelectedForCompare] = useState<Set<string>>(
    new Set()
  );

  useEffect(() => {
    loadData();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelId, page]);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [modelData, executionsData] = await Promise.all([
        api.getMyModel(modelId),
        api.getModelExecutions(modelId, { page, page_size: 20 }),
      ]);
      setModel(modelData);
      setExecutions(executionsData.items);
      setTotalPages(Math.ceil(executionsData.total / executionsData.page_size));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("failedToLoad"));
    } finally {
      setLoading(false);
    }
  };

  // Filter executions by origin for both the table and the chart
  const filteredExecutions = useMemo(
    () =>
      executions.filter(
        (e) => !originFilter || (e.origin ?? "manual") === originFilter
      ),
    [executions, originFilter]
  );

  const getStatusColor = (status: string) => {
    switch (status) {
      case "completed":
        return "bg-green-100 text-green-800";
      case "failed":
        return "bg-red-100 text-red-800";
      case "running":
        return "bg-blue-100 text-blue-800";
      default:
        return "bg-gray-100 text-gray-800";
    }
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString();
  };

  const toggleCompare = (executionId: string) => {
    setSelectedForCompare((prev) => {
      const next = new Set(prev);
      if (next.has(executionId)) {
        next.delete(executionId);
      } else if (next.size < 2) {
        next.add(executionId);
      }
      return next;
    });
  };

  const handleCompareSelected = () => {
    const [idA, idB] = Array.from(selectedForCompare);
    router.push(`/solve/executions/compare?a=${idA}&b=${idB}`);
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

  if (error) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-6 text-center">
          <p className="text-destructive mb-4">{error}</p>
          <Button onClick={loadData}>{t("retry")}</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="mb-6">
        <Link
          href={`/solve/${modelId}`}
          className="text-sm text-muted-foreground hover:text-foreground mb-2 inline-block"
        >
          &larr; {t("backToModel")}
        </Link>
        <h1 className="text-2xl font-bold text-foreground">
          {t("title", { modelName: model?.display_name || model?.custom_name || "Model" })}
        </h1>
        <p className="text-muted-foreground">
          {t("subtitle")}
        </p>
      </div>

      {model && (
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="bg-card border border-border rounded-lg p-4 text-center">
            <div className="text-2xl font-bold text-foreground">{model.total_executions}</div>
            <div className="text-sm text-muted-foreground">{t("totalRuns")}</div>
          </div>
          <div className="bg-card border border-border rounded-lg p-4 text-center">
            <div className="text-2xl font-bold text-foreground">{model.total_credits_used}</div>
            <div className="text-sm text-muted-foreground">{t("creditsUsed")}</div>
          </div>
          <div className="bg-card border border-border rounded-lg p-4 text-center">
            <div className="text-2xl font-bold text-foreground">
              {model.last_executed_at ? formatDate(model.last_executed_at) : t("never")}
            </div>
            <div className="text-sm text-muted-foreground">{t("lastRun")}</div>
          </div>
        </div>
      )}

      <div className="flex items-center gap-4 mb-4">
        <select
          value={originFilter}
          onChange={(e) => setOriginFilter(e.target.value)}
          className="px-3 py-2 rounded-md border bg-background text-sm"
        >
          <option value="">{t("allOrigins")}</option>
          <option value="manual">{t("manual")}</option>
          <option value="triggered">{t("triggered")}</option>
        </select>
        <span className="text-sm text-muted-foreground">
          {t("executionCount", { count: filteredExecutions.length })}
          {originFilter ? ` (${originFilter})` : ""}
        </span>
      </div>

      {/* Objective Trend Chart — uses filteredExecutions so origin filter drives chart data */}
      {filteredExecutions.length > 0 && (
        <div className="bg-card border border-border rounded-lg p-6 mb-6">
          <h2 className="text-lg font-semibold text-foreground mb-4">
            {t("objectiveValueTrend")}
          </h2>
          <ObjectiveTrendChart executions={filteredExecutions} />
        </div>
      )}

      {executions.length === 0 ? (
        <div className="bg-card border border-border rounded-lg p-12 text-center">
          <div className="text-4xl mb-4">📋</div>
          <h3 className="text-lg font-semibold mb-2">{t("noExecutions")}</h3>
          <p className="text-muted-foreground mb-4">
            {t("noExecutionsDescription")}
          </p>
          <Button onClick={() => router.push(`/solve/${modelId}`)}>
            {t("runModel")}
          </Button>
        </div>
      ) : (
        <>
          {/* Compare Selected button — shown only when exactly 2 are selected */}
          <div className="flex justify-end mb-3 min-h-[36px]">
            {selectedForCompare.size === 2 && (
              <Button variant="default" onClick={handleCompareSelected}>
                {t("compareSelected")}
              </Button>
            )}
          </div>

          <div className="bg-card border border-border rounded-lg overflow-hidden">
            <table className="w-full">
              <thead className="bg-muted/50">
                <tr>
                  <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">{t("tableHeaders.compare")}</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">{t("tableHeaders.date")}</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">{t("tableHeaders.status")}</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">{t("tableHeaders.origin")}</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">{t("tableHeaders.objective")}</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">{t("tableHeaders.duration")}</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">{t("tableHeaders.credits")}</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">{t("tableHeaders.actions")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {filteredExecutions.map((execution) => {
                  const isCompleted = execution.status === "completed";
                  const isChecked = selectedForCompare.has(execution.id);
                  const isDisabled =
                    !isCompleted ||
                    (selectedForCompare.size === 2 && !isChecked);

                  return (
                    <tr key={execution.id} className="hover:bg-muted/30">
                      {/* Compare checkbox — only for completed executions */}
                      <td className="px-4 py-3">
                        {isCompleted ? (
                          <input
                            type="checkbox"
                            checked={isChecked}
                            disabled={isDisabled}
                            onChange={() => toggleCompare(execution.id)}
                            className="w-4 h-4 rounded border-border accent-primary cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
                            title={
                              isDisabled && !isChecked
                                ? t("deselectToChoose")
                                : t("selectForComparison")
                            }
                          />
                        ) : (
                          <span className="text-muted-foreground/40 text-xs">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm">
                        {formatDate(execution.created_at)}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(
                            execution.status
                          )}`}
                        >
                          {statusLabel(execution.status)}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <OriginBadge
                          origin={execution.origin}
                          triggerName={execution.input_data?.trigger_name as string | undefined}
                        />
                      </td>
                      <td className="px-4 py-3 text-sm text-muted-foreground font-mono">
                        {execution.objective_value != null
                          ? execution.objective_value.toLocaleString(undefined, {
                              maximumFractionDigits: 4,
                            })
                          : "—"}
                      </td>
                      <td className="px-4 py-3 text-sm text-muted-foreground">
                        {execution.execution_time_ms
                          ? `${execution.execution_time_ms}ms`
                          : "-"}
                      </td>
                      <td className="px-4 py-3 text-sm">
                        {execution.credits_consumed}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() =>
                              router.push(
                                `/solve/executions/${execution.id}`
                              )
                            }
                          >
                            {t("view")}
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              // Store input in sessionStorage and redirect to run page
                              sessionStorage.setItem(
                                `rerun_input_${modelId}`,
                                JSON.stringify(execution.input_data, null, 2)
                              );
                              router.push(`/solve/${modelId}?rerun=true`);
                            }}
                            title={t("runAgainWithInput")}
                          >
                            <Play className="w-4 h-4 mr-1" /> {t("rerun")}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              navigator.clipboard.writeText(
                                JSON.stringify(execution.input_data, null, 2)
                              );
                            }}
                            title={t("copyInputToClipboard")}
                          >
                            <Copy className="w-4 h-4" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {filteredExecutions.length === 0 && executions.length > 0 && (
              <div className="text-center py-8 text-muted-foreground text-sm">
                {t("noFilterMatch")}
              </div>
            )}
          </div>

          {totalPages > 1 && (
            <div className="flex justify-center gap-2 mt-6">
              <Button
                variant="outline"
                disabled={page === 1}
                onClick={() => setPage(page - 1)}
              >
                {t("previous")}
              </Button>
              <span className="px-4 py-2 text-sm">
                {t("pageOf", { page, totalPages })}
              </span>
              <Button
                variant="outline"
                disabled={page === totalPages}
                onClick={() => setPage(page + 1)}
              >
                {t("next")}
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
