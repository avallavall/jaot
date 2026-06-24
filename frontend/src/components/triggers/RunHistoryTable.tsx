"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type { TriggerRun, TriggerRunStatus } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Copy, Check, RefreshCw, Eye, CheckCircle, XCircle, ExternalLink } from "lucide-react";

interface RunHistoryTableProps {
  triggerId: string;
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays === 1) return "Yesterday";
  return date.toLocaleDateString();
}

function formatDuration(ms?: number): string {
  if (ms === undefined || ms === null) return "\u2014";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function StatusBadge({ status, t }: { status: TriggerRunStatus; t: (key: string) => string }) {
  const config: Record<TriggerRunStatus, { labelKey: string; className: string }> = {
    pending: { labelKey: "statusPending", className: "bg-yellow-100 text-yellow-800 border-yellow-200 dark:bg-yellow-900/30 dark:text-yellow-300" },
    running: { labelKey: "statusRunning", className: "bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-900/30 dark:text-blue-300" },
    completed: { labelKey: "statusCompleted", className: "bg-green-100 text-green-800 border-green-200 dark:bg-green-900/30 dark:text-green-300" },
    failed: { labelKey: "statusFailed", className: "bg-red-100 text-red-800 border-red-200 dark:bg-red-900/30 dark:text-red-300" },
    timeout: { labelKey: "statusTimeout", className: "bg-orange-100 text-orange-800 border-orange-200 dark:bg-orange-900/30 dark:text-orange-300" },
    validation_failed: { labelKey: "statusValidationFailed", className: "bg-purple-100 text-purple-800 border-purple-200 dark:bg-purple-900/30 dark:text-purple-300" },
    skipped_credits: { labelKey: "statusSkippedCredits", className: "bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-900/30 dark:text-amber-300" },
    skipped_overlap: { labelKey: "statusSkippedOverlap", className: "bg-gray-100 text-gray-800 border-gray-200 dark:bg-gray-900/30 dark:text-gray-300" },
  };
  const { labelKey, className } = config[status] ?? { labelKey: status, className: "" };
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${className}`}>
      {t(labelKey)}
    </span>
  );
}

function CopyableId({ id }: { id: string }) {
  const [copied, setCopied] = useState(false);
  const short = id.slice(0, 16) + "...";

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // ignore
    }
  };

  return (
    <button
      onClick={handleCopy}
      className="inline-flex items-center gap-1 font-mono text-xs text-muted-foreground hover:text-foreground transition-colors"
      title={id}
    >
      {short}
      {copied ? <Check className="w-3 h-3 text-green-500" /> : <Copy className="w-3 h-3" />}
    </button>
  );
}

// Run Detail Modal
function RunDetailModal({ run, open, onClose, t }: { run: TriggerRun; open: boolean; onClose: () => void; t: (key: string, values?: Record<string, string | number>) => string }) {
  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onClose(); }}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("runDetails")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <div className="text-xs text-muted-foreground mb-1">{t("runId")}</div>
              <code className="text-xs font-mono break-all">{run.id}</code>
            </div>
            <div>
              <div className="text-xs text-muted-foreground mb-1">{t("headerStatus")}</div>
              <StatusBadge status={run.status} t={t} />
            </div>
            <div>
              <div className="text-xs text-muted-foreground mb-1">{t("creditsConsumed")}</div>
              <div>{run.credits_consumed}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground mb-1">{t("duration")}</div>
              <div>{formatDuration(run.execution_time_ms)}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground mb-1">{t("webhookDelivered")}</div>
              <div>
                {run.webhook_delivered === true ? (
                  <span className="flex items-center gap-1 text-green-600"><CheckCircle className="w-4 h-4" /> {t("webhookYes")}</span>
                ) : run.webhook_delivered === false ? (
                  <span className="flex items-center gap-1 text-red-600"><XCircle className="w-4 h-4" /> {t("webhookNo")}</span>
                ) : "\u2014"}
                {run.webhook_attempts > 0 && (
                  <span className="text-xs text-muted-foreground ml-1">{t("webhookAttempts", { count: run.webhook_attempts })}</span>
                )}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground mb-1">{t("createdAt")}</div>
              <div className="text-xs">{new Date(run.created_at).toLocaleString()}</div>
            </div>
          </div>

          {run.error_message && (
            <div>
              <div className="text-xs text-muted-foreground mb-1 font-medium">{t("errorMessage")}</div>
              <div className="bg-destructive/10 text-destructive text-sm rounded p-3 font-mono">
                {run.error_message}
              </div>
            </div>
          )}

          {run.override_data && Object.keys(run.override_data).length > 0 && (
            <div>
              <div className="text-xs text-muted-foreground mb-1 font-medium">{t("overrideData")}</div>
              <pre className="bg-muted rounded p-3 text-xs overflow-x-auto">
                {JSON.stringify(run.override_data, null, 2)}
              </pre>
            </div>
          )}

          {run.result_data && (
            <div>
              <div className="text-xs text-muted-foreground mb-1 font-medium">{t("resultData")}</div>
              <pre className="bg-muted rounded p-3 text-xs overflow-x-auto max-h-64">
                {JSON.stringify(run.result_data, null, 2)}
              </pre>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function RunHistoryTable({ triggerId }: RunHistoryTableProps) {
  const router = useRouter();
  const t = useTranslations("triggers.runHistory");
  const tc = useTranslations("common");
  const [runs, setRuns] = useState<TriggerRun[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [rerunning, setRerunning] = useState<Record<string, boolean>>({});
  const [selectedRun, setSelectedRun] = useState<TriggerRun | null>(null);
  const pageSize = 20;

  const loadRuns = useCallback(async (p: number) => {
    setLoading(true);
    try {
      const data = await api.triggers.runs.list(triggerId, p, pageSize);
      setRuns(data.items);
      setTotal(data.total);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("loadError"));
    } finally {
      setLoading(false);
    }
  }, [triggerId, t]);

  useEffect(() => {
    loadRuns(page);
  }, [loadRuns, page]);

  const handleRerun = async (run: TriggerRun) => {
    setRerunning((prev) => ({ ...prev, [run.id]: true }));
    try {
      await api.triggers.runs.rerun(triggerId, run.id);
      toast.success(t("rerunQueued"));
      // Refresh after a short delay to show new run
      setTimeout(() => loadRuns(page), 1000);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("rerunError"));
    } finally {
      setRerunning((prev) => ({ ...prev, [run.id]: false }));
    }
  };

  const totalPages = Math.ceil(total / pageSize);

  if (loading && runs.length === 0) {
    return (
      <div className="space-y-2">
        {[...Array(3)].map((_, i) => (
          <Skeleton key={i} className="h-14 w-full" />
        ))}
      </div>
    );
  }

  if (!loading && runs.length === 0) {
    return (
      <div className="text-center py-12 border-2 border-dashed rounded-lg">
        <p className="text-muted-foreground font-medium">{t("noRuns")}</p>
        <p className="text-sm text-muted-foreground mt-1">
          {t("noRunsDescription")}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {t("showing", {
            start: Math.min((page - 1) * pageSize + 1, total),
            end: Math.min(page * pageSize, total),
            total,
          })}
        </p>
        <Button variant="ghost" size="sm" onClick={() => loadRuns(page)} disabled={loading}>
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
        </Button>
      </div>

      <div className="border rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/50">
              <th className="text-left px-4 py-2 text-xs font-medium text-muted-foreground">{t("headerStatus")}</th>
              <th className="text-left px-4 py-2 text-xs font-medium text-muted-foreground">{t("headerRunId")}</th>
              <th className="text-left px-4 py-2 text-xs font-medium text-muted-foreground">{t("headerCredits")}</th>
              <th className="text-left px-4 py-2 text-xs font-medium text-muted-foreground">{t("headerDuration")}</th>
              <th className="text-left px-4 py-2 text-xs font-medium text-muted-foreground">{t("headerOverrides")}</th>
              <th className="text-left px-4 py-2 text-xs font-medium text-muted-foreground">{t("headerWebhook")}</th>
              <th className="text-left px-4 py-2 text-xs font-medium text-muted-foreground">{t("headerTime")}</th>
              <th className="text-right px-4 py-2 text-xs font-medium text-muted-foreground">{t("headerActions")}</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.id} className="border-b last:border-0 hover:bg-muted/30 transition-colors">
                <td className="px-4 py-3">
                  <StatusBadge status={run.status} t={t} />
                </td>
                <td className="px-4 py-3">
                  <CopyableId id={run.id} />
                </td>
                <td className="px-4 py-3 tabular-nums">
                  {run.credits_consumed}
                </td>
                <td className="px-4 py-3 tabular-nums text-muted-foreground">
                  {formatDuration(run.execution_time_ms)}
                </td>
                <td className="px-4 py-3">
                  {run.override_data && Object.keys(run.override_data).length > 0 ? (
                    <button
                      onClick={() => setSelectedRun(run)}
                      className="text-primary text-xs underline hover:no-underline"
                    >
                      {t("overridesYes")}
                    </button>
                  ) : (
                    <span className="text-muted-foreground text-xs">{t("overridesNone")}</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  {run.webhook_delivered === true ? (
                    <CheckCircle className="w-4 h-4 text-green-500" />
                  ) : run.webhook_delivered === false ? (
                    <XCircle className="w-4 h-4 text-red-500" />
                  ) : (
                    <span className="text-muted-foreground text-xs">{"\u2014"}</span>
                  )}
                </td>
                <td className="px-4 py-3 text-muted-foreground text-xs">
                  {formatDate(run.created_at)}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-1">
                    {run.execution_id ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => router.push(`/solve/executions/${run.execution_id}`)}
                        title={t("viewRunDetails")}
                        className="h-7 px-2"
                      >
                        <ExternalLink className="w-3.5 h-3.5 mr-1" />
                        <span className="text-xs">{t("viewExecution")}</span>
                      </Button>
                    ) : (run.status === "failed" || run.status === "validation_failed") ? (
                      <span className="text-xs text-muted-foreground">{t("executionUnavailable")}</span>
                    ) : (run.status === "pending" || run.status === "running") ? (
                      <span className="text-xs text-muted-foreground animate-pulse">{t("starting")}</span>
                    ) : null}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setSelectedRun(run)}
                      title={t("viewRunDetails")}
                      className="h-7 px-2"
                    >
                      <Eye className="w-3.5 h-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleRerun(run)}
                      disabled={rerunning[run.id]}
                      title={t("rerunTitle")}
                      className="h-7 px-2"
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${rerunning[run.id] ? "animate-spin" : ""}`} />
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1 || loading}
          >
            {tc("previous")}
          </Button>
          <span className="text-sm text-muted-foreground">
            {t("pageInfo", { page, totalPages })}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages || loading}
          >
            {tc("next")}
          </Button>
        </div>
      )}

      {selectedRun && (
        <RunDetailModal run={selectedRun} open={!!selectedRun} onClose={() => setSelectedRun(null)} t={t} />
      )}
    </div>
  );
}
