"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { api, ExecutionSummary } from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";
import { Database, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { useCommonLabels } from "@/hooks/useCommonLabels";
import { OriginBadge } from "@/components/solve/OriginBadge";
import { ORIGIN_KEYS, executionOriginHref } from "@/lib/execution-origin";
import { EmptyState } from "@/components/guidance/EmptyState";
import { apiDate } from "@/lib/dates";

// The filter goes to `?origin=`, which the backend matches against the origin
// column — so `model_project` is left out: it is a source_kind, and offering it
// here would be a filter that always returns nothing.
const ORIGIN_FILTER_KEYS = ORIGIN_KEYS.filter((key) => key !== "model_project");

// Every status the backend can store (app/models/optimization_model.py:ExecutionStatus).
// Kept whole so a status the table can paint is also a status the filter can reach —
// "cancelled" and "timeout" were both showing up in rows with no way to filter for them.
const STATUS_FILTER_KEYS = [
  "completed",
  "failed",
  "running",
  "pending",
  "cancelled",
  "timeout",
] as const;

export default function ExecutionsPage() {
  const t = useTranslations("solve.executions");
  const tOrigin = useTranslations("solve.origin");
  const { statusLabel } = useCommonLabels();
  const router = useRouter();
  const [executions, setExecutions] = useState<ExecutionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [originFilter, setOriginFilter] = useState<string>("");
  // The comparison view is a finished screen that nothing linked to: the only way
  // in was typing two execution ids into a free-text box on the analytics page.
  // Pick two rows here instead (owner, 2026-08-02: surface it, do not delete it).
  const [selected, setSelected] = useState<string[]>([]);

  // The comparison view takes exactly two (`?a=&b=`), so selecting a third drops
  // the oldest pick rather than silently refusing the click.
  const toggleSelected = (id: string) =>
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id].slice(-2),
    );

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
          {STATUS_FILTER_KEYS.map((status) => (
            <option key={status} value={status}>
              {statusLabel(status)}
            </option>
          ))}
        </select>

        <select
          value={originFilter}
          onChange={(e) => { setOriginFilter(e.target.value); setPage(1); }}
          className="px-3 py-2 rounded-md border bg-background text-sm"
        >
          <option value="">{t("allOrigins")}</option>
          {ORIGIN_FILTER_KEYS.map((key) => (
            <option key={key} value={key}>
              {tOrigin(key)}
            </option>
          ))}
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

      {!loading && selected.length > 0 && (
        <div className="mb-3 flex items-center gap-3 rounded-md bg-muted/40 px-3 py-2 text-sm">
          <span className="text-muted-foreground">
            {t("selectedCount", { count: selected.length })}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setSelected([])}>
              {t("clearSelection")}
            </Button>
            <Button
              size="sm"
              disabled={selected.length !== 2}
              title={selected.length !== 2 ? t("selectTwoHint") : undefined}
              data-testid="executions-compare"
              onClick={() =>
                router.push(
                  `/solve/executions/compare?a=${selected[0]}&b=${selected[1]}`,
                )
              }
            >
              {t("compareSelected")}
            </Button>
          </div>
        </div>
      )}

      {!loading && (
        <div className="bg-card border rounded-lg overflow-hidden">
          <table className="w-full">
            <thead className="bg-muted/50">
              <tr>
                <th className="w-10 px-4 py-3" aria-label={t("selectToCompare")} />
                <th className="text-left px-4 py-3 text-sm font-medium">{t("tableHeaders.status")}</th>
                <th className="text-left px-4 py-3 text-sm font-medium">{t("tableHeaders.origin")}</th>
                <th className="text-left px-4 py-3 text-sm font-medium">{t("tableHeaders.model")}</th>
                <th className="text-left px-4 py-3 text-sm font-medium">{t("tableHeaders.result")}</th>
                <th className="text-right px-4 py-3 text-sm font-medium">{t("tableHeaders.time")}</th>
                <th className="text-right px-4 py-3 text-sm font-medium">{t("tableHeaders.date")}</th>
                <th className="text-right px-4 py-3 text-sm font-medium">{t("tableHeaders.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {executions.map((exec) => (
                <tr key={exec.id} className="border-t hover:bg-muted/30">
                  <td className="px-4 py-3">
                    <input
                      type="checkbox"
                      checked={selected.includes(exec.id)}
                      onChange={() => toggleSelected(exec.id)}
                      aria-label={t("selectRow", { id: exec.id })}
                      data-testid="execution-select"
                      className="h-4 w-4 accent-primary"
                    />
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(exec.status)}`}>
                      {statusLabel(exec.status)}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <OriginBadge
                      origin={exec.origin}
                      sourceKind={exec.source_kind ?? undefined}
                      triggerName={exec.trigger_name ?? undefined}
                    />
                  </td>
                  <td className="px-4 py-3">
                    {(() => {
                      const href =
                        executionOriginHref(exec.origin, exec.source_id, exec.source_kind) ??
                        (exec.organization_model_id
                          ? `/solve/${exec.organization_model_id}`
                          : null);
                      const label = exec.model_name ?? (href ? t("openSource") : t("external"));
                      const content = (
                        <>
                          <span className="text-sm">{label}</span>
                          {exec.model_author && (
                            <span className="text-xs text-muted-foreground">
                              {" · "}
                              {exec.model_author}
                            </span>
                          )}
                        </>
                      );
                      return href ? (
                        <Link href={href} className="text-primary hover:underline">
                          {content}
                        </Link>
                      ) : (
                        <span className="text-muted-foreground">{content}</span>
                      );
                    })()}
                    {/* §8/S1: which dataset (scenario) the run was compiled against. */}
                    {exec.dataset_name && (
                      <span
                        data-testid="execution-dataset-badge"
                        title={t("datasetBadge")}
                        className="ml-2 inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200"
                      >
                        <Database className="h-3 w-3" />
                        {exec.dataset_name}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {exec.status === "completed" && exec.objective_value != null ? (
                      <span className="font-mono">{exec.objective_value.toFixed(2)}</span>
                    ) : exec.error_message ? (
                      <span className="text-destructive text-xs truncate max-w-[200px] block">
                        {exec.error_message}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">-</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right text-sm text-muted-foreground">
                    {exec.execution_time_ms ? `${exec.execution_time_ms}ms` : "-"}
                  </td>
                  <td className="px-4 py-3 text-right text-sm text-muted-foreground">
                    {apiDate(exec.created_at).toLocaleString()}
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
