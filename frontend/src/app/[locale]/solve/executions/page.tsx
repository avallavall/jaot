"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { api, ModelExecution } from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";
import { Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTranslations } from "next-intl";
import { useCommonLabels } from "@/hooks/useCommonLabels";
import { OriginBadge } from "@/components/solve/OriginBadge";
import { EmptyState } from "@/components/guidance/EmptyState";

export default function ExecutionsPage() {
  const t = useTranslations("solve.executions");
  const { statusLabel } = useCommonLabels();
  const router = useRouter();
  const [executions, setExecutions] = useState<ModelExecution[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [originFilter, setOriginFilter] = useState<string>("");

  const pageSize = 20;

  useEffect(() => {
    loadExecutions();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, statusFilter, originFilter]);

  const loadExecutions = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.getAllExecutions({
        status: statusFilter || undefined,
        origin: originFilter || undefined,
        page,
        page_size: pageSize,
      });
      setExecutions(result.items);
      setTotal(result.total);
    } catch (err) {
      setError(getErrorMessage(err, t("failedToLoad")));
    } finally {
      setLoading(false);
    }
  };

  const totalPages = Math.ceil(total / pageSize);

  const getStatusColor = (status: string) => {
    switch (status) {
      case "completed":
        return "bg-green-100 text-green-800";
      case "failed":
        return "bg-red-100 text-red-800";
      case "running":
        return "bg-blue-100 text-blue-800";
      case "pending":
        return "bg-yellow-100 text-yellow-800";
      default:
        return "bg-gray-100 text-gray-800";
    }
  };

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-foreground mb-2">{t("title")}</h1>
        <p className="text-muted-foreground">
          {t("subtitle")}
        </p>
      </div>

      <div className="flex items-center gap-4 mb-6">
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
          className="px-3 py-2 rounded-md border bg-background text-sm"
        >
          <option value="">{t("allStatus")}</option>
          <option value="completed">{t("completed")}</option>
          <option value="failed">{t("failed")}</option>
          <option value="running">{t("running")}</option>
          <option value="pending">{t("pending")}</option>
        </select>

        <select
          value={originFilter}
          onChange={(e) => { setOriginFilter(e.target.value); setPage(1); }}
          className="px-3 py-2 rounded-md border bg-background text-sm"
        >
          <option value="">{t("allOrigins")}</option>
          <option value="manual">{t("manual")}</option>
          <option value="triggered">{t("triggered")}</option>
        </select>

        <span className="text-sm text-muted-foreground">
          {t("totalExecutions", { count: total })}
        </span>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-destructive/10 text-destructive rounded-lg">
          {error}
        </div>
      )}

      {loading && (
        <div className="flex justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
        </div>
      )}

      {!loading && (
        <div className="bg-card border rounded-lg overflow-hidden">
          <table className="w-full">
            <thead className="bg-muted/50">
              <tr>
                <th className="text-left px-4 py-3 text-sm font-medium">{t("tableHeaders.status")}</th>
                <th className="text-left px-4 py-3 text-sm font-medium">{t("tableHeaders.origin")}</th>
                <th className="text-left px-4 py-3 text-sm font-medium">{t("tableHeaders.model")}</th>
                <th className="text-left px-4 py-3 text-sm font-medium">{t("tableHeaders.result")}</th>
                <th className="text-right px-4 py-3 text-sm font-medium">{t("tableHeaders.credits")}</th>
                <th className="text-right px-4 py-3 text-sm font-medium">{t("tableHeaders.time")}</th>
                <th className="text-right px-4 py-3 text-sm font-medium">{t("tableHeaders.date")}</th>
                <th className="text-right px-4 py-3 text-sm font-medium">{t("tableHeaders.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {executions.map((exec) => (
                <tr key={exec.id} className="border-t hover:bg-muted/30">
                  <td className="px-4 py-3">
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(exec.status)}`}>
                      {statusLabel(exec.status)}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <OriginBadge
                      origin={exec.origin}
                      triggerName={exec.input_data?.trigger_name as string | undefined}
                    />
                  </td>
                  <td className="px-4 py-3">
                    {exec.organization_model_id ? (
                      <button
                        onClick={() => router.push(`/solve/${exec.organization_model_id}`)}
                        className="text-sm hover:text-primary"
                      >
                        {exec.organization_model_id.slice(0, 8)}...
                      </button>
                    ) : (
                      <span className="text-sm text-muted-foreground">{t("external")}</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {exec.status === "completed" && exec.result_data?.objective_value != null ? (
                      <span className="font-mono">
                        {exec.result_data.objective_value.toFixed(2)}
                      </span>
                    ) : exec.error_message ? (
                      <span className="text-destructive text-xs truncate max-w-[200px] block">
                        {exec.error_message}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">-</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right text-sm">
                    {exec.credits_consumed}
                  </td>
                  <td className="px-4 py-3 text-right text-sm text-muted-foreground">
                    {exec.execution_time_ms ? `${exec.execution_time_ms}ms` : "-"}
                  </td>
                  <td className="px-4 py-3 text-right text-sm text-muted-foreground">
                    {new Date(exec.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => router.push(`/solve/executions/${exec.id}`)}
                    >
                      {t("view")}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {executions.length === 0 && (
            <div className="py-6">
              <EmptyState
                icon={<Play className="h-12 w-12" />}
                title={t("noExecutions")}
                description={t("noExecutionsDescription")}
                expertDescription={t("noExecutionsExpert")}
                actionLabel={t("goToModels")}
                actionHref="/solve"
              />
            </div>
          )}
        </div>
      )}

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
    </div>
  );
}
