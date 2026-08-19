"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  api,
  type SolveAnalyticsSummary,
  type SolveAnalyticsTrends,
  type SolveAnalyticsCompare,
} from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";
import { buildOriginSlices } from "@/lib/execution-origin";
import { useCommonLabels } from "@/hooks/useCommonLabels";
import { Button } from "@/components/ui/button";
import { AnalyticsStatusTiles } from "@/components/solve/AnalyticsStatusTiles";
import { OriginBadge } from "@/components/solve/OriginBadge";
import {
  DistributionPieCard,
  type PieEntry,
} from "@/components/solve/DistributionPieCard";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  BarChart2,
  Clock,
  CheckCircle,
  Plus,
  X,
  ArrowLeft,
} from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

type Period = 7 | 30 | 90 | 0;
type Bucket = "day" | "week";

const PERIOD_OPTIONS: { value: Period; labelKey: string }[] = [
  { value: 7, labelKey: "days7" },
  { value: 30, labelKey: "days30" },
  { value: 90, labelKey: "days90" },
  { value: 0, labelKey: "allTime" },
];

const STATUS_COLORS: Record<string, string> = {
  completed: "#22c55e",
  failed: "#ef4444",
  timeout: "#eab308",
  running: "#3b82f6",
  pending: "#9ca3af",
};

function formatMs(ms: number | null): string {
  if (ms == null) return "-";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function formatPct(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

export default function SolveAnalyticsPage() {
  const t = useTranslations("solve.analytics");
  // Origin labels live in one namespace shared with the badge — see execution-origin.
  const tOrigin = useTranslations("solve.origin");
  const { statusLabel } = useCommonLabels();
  const router = useRouter();

  const [period, setPeriod] = useState<Period>(30);
  const [bucket, setBucket] = useState<Bucket>("day");
  const [summary, setSummary] = useState<SolveAnalyticsSummary | null>(null);
  const [trends, setTrends] = useState<SolveAnalyticsTrends | null>(null);
  const [compareData, setCompareData] = useState<SolveAnalyticsCompare | null>(null);
  const [comparing, setComparing] = useState(false);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [compareInput, setCompareInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async (p: Period, b: Bucket) => {
    setLoading(true);
    setError(null);
    try {
      const [s, tr] = await Promise.all([
        api.solveAnalytics.getSummary(p),
        api.solveAnalytics.getTrends(p, b),
      ]);
      setSummary(s);
      setTrends(tr);
    } catch (err) {
      setError(getErrorMessage(err, t("failedToLoad")));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    loadData(period, bucket);
  }, [period, bucket, loadData]);

  const handleCompare = useCallback(async () => {
    if (compareIds.length < 2) return;
    setComparing(true);
    setError(null);
    try {
      const data = await api.solveAnalytics.compare(compareIds);
      setCompareData(data);
    } catch (err) {
      setCompareData(null);
      setError(getErrorMessage(err, t("failedToLoad")));
    } finally {
      setComparing(false);
    }
  }, [compareIds, t]);

  // IDs the user asked to compare that the backend did not return (don't exist
  // or aren't in this org). Surfacing them is the whole point: an empty result
  // used to render nothing at all ("nothing happens on Compare").
  const comparedMissingIds = useMemo(
    () =>
      compareData
        ? compareIds.filter((id) => !compareData.executions.some((e) => e.id === id))
        : [],
    [compareData, compareIds],
  );

  const addCompareId = () => {
    const id = compareInput.trim();
    if (!id) return;
    setCompareIds((prev) => (prev.includes(id) ? prev : [...prev, id]));
    setCompareInput("");
  };

  const removeCompareId = (id: string) => {
    setCompareIds((prev) => prev.filter((i) => i !== id));
    setCompareData((prev) =>
      prev ? { executions: prev.executions.filter((e) => e.id !== id) } : null,
    );
  };

  // Prepare chart data (memoized to avoid re-derivation on unrelated renders)
  // Labels come from the same statusLabel() the executions list uses, so the donut
  // says "Completada" where the table says "Completada" — not a CSS-capitalized
  // "Completed" straight out of the API.
  const statusData = useMemo<PieEntry[]>(
    () =>
      summary
        ? Object.entries(summary.executions_by_status).map(([status, value]) => ({
            name: statusLabel(status),
            value,
            fill: STATUS_COLORS[status] || "#9ca3af",
          }))
        : [],
    [summary, statusLabel],
  );

  // One slice per origin the backend reports, largest first. The mapping itself
  // lives in the library, where it is asserted directly — it is what carried the
  // reported defect.
  const originData = useMemo<PieEntry[]>(
    () => (summary ? buildOriginSlices(summary.executions_by_origin, tOrigin) : []),
    [summary, tOrigin],
  );

  const solverStatusData = useMemo(
    () =>
      summary
        ? Object.entries(summary.solver_status_distribution).map(([name, value]) => ({
            name,
            value,
          }))
        : [],
    [summary],
  );

  if (loading && !summary) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-muted rounded w-1/3" />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-24 bg-muted rounded" />
            ))}
          </div>
          <div className="h-64 bg-muted rounded" />
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="mb-6">
        <button
          onClick={() => router.push("/solve/executions")}
          className="text-sm text-muted-foreground hover:text-foreground mb-2 inline-flex items-center gap-1"
        >
          <ArrowLeft className="w-3 h-3" />
          {t("executions")}
        </button>
        <h1 className="text-2xl font-bold text-foreground">{t("title")}</h1>
        <p className="text-muted-foreground text-sm mt-1">{t("description")}</p>
      </div>

      <div className="flex items-center gap-2 mb-6">
        <span className="text-sm text-muted-foreground">{t("period")}:</span>
        {PERIOD_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            onClick={() => setPeriod(opt.value)}
            className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
              period === opt.value
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:bg-muted/80"
            }`}
          >
            {t(opt.labelKey)}
          </button>
        ))}
      </div>

      {error && (
        <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-4 mb-6">
          <p className="text-destructive text-sm">{error}</p>
        </div>
      )}

      {summary && summary.total_executions === 0 ? (
        <div className="bg-card border border-border rounded-lg p-12 text-center">
          <BarChart2 className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
          <p className="text-muted-foreground">{t("noData")}</p>
        </div>
      ) : summary && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div className="bg-card border border-border rounded-lg p-4">
              <div className="flex items-center gap-2 text-muted-foreground mb-1">
                <BarChart2 className="w-4 h-4" />
                <span className="text-sm">{t("totalExecutions")}</span>
              </div>
              <div className="text-2xl font-bold">{summary.total_executions}</div>
            </div>
            <div className="bg-card border border-border rounded-lg p-4">
              <div className="flex items-center gap-2 text-muted-foreground mb-1">
                <CheckCircle className="w-4 h-4" />
                <span className="text-sm">{t("successRate")}</span>
              </div>
              <div className="text-2xl font-bold text-green-600">
                {/* A one-decimal percentage over a handful of runs reads as
                    statistics it is not: below 20 runs the honest figure is
                    the plain ratio. */}
                {summary.total_executions < 20
                  ? `${summary.completed}/${summary.total_executions}`
                  : formatPct(summary.success_rate)}
              </div>
            </div>
            <div className="bg-card border border-border rounded-lg p-4">
              <div className="flex items-center gap-2 text-muted-foreground mb-1">
                <Clock className="w-4 h-4" />
                <span className="text-sm">{t("avgSolveTime")}</span>
              </div>
              <div className="text-2xl font-bold">{formatMs(summary.avg_solve_time_ms)}</div>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            <AnalyticsStatusTiles byStatus={summary.executions_by_status} />
            <div className="bg-card border border-border rounded-lg p-3 text-center">
              <div className="text-xs text-muted-foreground">{t("medianSolveTime")}</div>
              <div className="text-lg font-semibold">{formatMs(summary.median_solve_time_ms)}</div>
            </div>
          </div>

          {/* Tabs: Trends / Distribution / Compare */}
          <Tabs defaultValue="trends">
            <TabsList className="mb-4">
              <TabsTrigger value="trends">{t("trends")}</TabsTrigger>
              <TabsTrigger value="distribution">{t("statusDistribution")}</TabsTrigger>
              <TabsTrigger value="compare">{t("compare")}</TabsTrigger>
            </TabsList>

            <TabsContent value="trends">
              <div className="bg-card border border-border rounded-lg p-4">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="font-semibold">{t("trends")}</h3>
                    <p className="text-sm text-muted-foreground">{t("trendsDescription")}</p>
                  </div>
                  <div className="flex gap-1">
                    <button
                      onClick={() => setBucket("day")}
                      className={`px-2 py-1 rounded text-xs font-medium ${
                        bucket === "day"
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {t("daily")}
                    </button>
                    <button
                      onClick={() => setBucket("week")}
                      className={`px-2 py-1 rounded text-xs font-medium ${
                        bucket === "week"
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {t("weekly")}
                    </button>
                  </div>
                </div>

                {trends && trends.data.length > 0 && trends.data.length < 3 ? (
                  /* One or two bars are not a trend: say what there is. */
                  <p className="text-muted-foreground text-sm py-8 text-center">
                    {t("sparseTrend", { count: summary.total_executions })}
                  </p>
                ) : trends && trends.data.length > 0 ? (
                  <div className="space-y-6">
                    <div>
                      <h4 className="text-sm font-medium text-muted-foreground mb-2">{t("executions")}</h4>
                      <ResponsiveContainer width="100%" height={240}>
                        <BarChart data={trends.data}>
                          <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                          <XAxis
                            dataKey="date"
                            tick={{ fontSize: 11 }}
                            tickFormatter={(d) => d.slice(5)}
                          />
                          <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                          <Tooltip
                            contentStyle={{ fontSize: 12 }}
                            labelFormatter={(d) => d}
                          />
                          <Bar dataKey="completed" stackId="a" fill="#22c55e" name={t("completed")} />
                          <Bar dataKey="failed" stackId="a" fill="#ef4444" name={t("failed")} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>

                  </div>
                ) : (
                  <p className="text-muted-foreground text-sm py-8 text-center">{t("noData")}</p>
                )}
              </div>
            </TabsContent>

            <TabsContent value="distribution">
              <div className="grid md:grid-cols-2 gap-4">
                <DistributionPieCard
                  title={t("statusDistribution")}
                  data={statusData}
                  noDataLabel={t("noData")}
                  formatSingle={(name, count) => t("singleCategory", { name, count })}
                />
                <DistributionPieCard
                  title={t("originDistribution")}
                  data={originData}
                  noDataLabel={t("noData")}
                  formatSingle={(name, count) => t("singleCategory", { name, count })}
                />

                <div className="bg-card border border-border rounded-lg p-4 md:col-span-2">
                  <h3 className="font-semibold mb-4">{t("solverStatusDistribution")}</h3>
                  {solverStatusData.length === 1 ? (
                    <p className="text-sm py-6">
                      {t("singleCategory", {
                        name: solverStatusData[0].name,
                        count: solverStatusData[0].value,
                      })}
                    </p>
                  ) : solverStatusData.length > 0 ? (
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={solverStatusData}>
                        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                        <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                        <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                        <Tooltip contentStyle={{ fontSize: 12 }} />
                        <Bar dataKey="value" fill="#6366f1" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  ) : (
                    <p className="text-muted-foreground text-sm">{t("noData")}</p>
                  )}
                </div>
              </div>
            </TabsContent>

            <TabsContent value="compare">
              <div className="bg-card border border-border rounded-lg p-4">
                <h3 className="font-semibold mb-1">{t("compareTitle")}</h3>
                <p className="text-sm text-muted-foreground mb-4">{t("compareDescription")}</p>

                <div className="flex gap-2 mb-4">
                  <input
                    type="text"
                    value={compareInput}
                    onChange={(e) => setCompareInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && addCompareId()}
                    placeholder={t("addExecution")}
                    className="flex-1 px-3 py-2 rounded-md border border-border bg-background text-sm"
                  />
                  <Button size="sm" onClick={addCompareId} disabled={!compareInput.trim()}>
                    <Plus className="w-4 h-4 mr-1" />
                    {t("add")}
                  </Button>
                  {compareIds.length >= 2 && (
                    <Button size="sm" onClick={handleCompare}>
                      {t("compare")}
                    </Button>
                  )}
                </div>

                {compareIds.length > 0 && (
                  <div className="flex flex-wrap gap-2 mb-4">
                    {compareIds.map((id) => (
                      <span
                        key={id}
                        className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-muted text-sm"
                      >
                        {id}
                        <button onClick={() => removeCompareId(id)}>
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                )}

                {comparing ? (
                  <p className="text-muted-foreground text-sm text-center py-8">
                    {t("comparing")}
                  </p>
                ) : compareData && compareData.executions.length > 0 ? (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-border">
                          <th className="text-left p-2 text-muted-foreground font-medium">ID</th>
                          <th className="text-left p-2 text-muted-foreground font-medium">{t("status")}</th>
                          <th className="text-left p-2 text-muted-foreground font-medium">{t("solverStatus")}</th>
                          <th className="text-right p-2 text-muted-foreground font-medium">{t("objectiveValue")}</th>
                          <th className="text-right p-2 text-muted-foreground font-medium">{t("solveTime")}</th>
                          <th className="text-right p-2 text-muted-foreground font-medium">{t("variables")}</th>
                          <th className="text-right p-2 text-muted-foreground font-medium">{t("constraints")}</th>
                          <th className="text-right p-2 text-muted-foreground font-medium">{t("gap")}</th>
                          <th className="text-left p-2 text-muted-foreground font-medium">{t("origin")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {compareData.executions.map((exe) => (
                          <tr
                            key={exe.id}
                            className="border-b border-border/50 hover:bg-muted/30 cursor-pointer"
                            onClick={() => router.push(`/solve/executions/${exe.id}`)}
                          >
                            <td className="p-2 font-mono text-xs">{exe.id.slice(0, 16)}...</td>
                            <td className="p-2">
                              <span
                                className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                                  exe.status === "completed"
                                    ? "bg-green-100 text-green-800"
                                    : exe.status === "failed"
                                      ? "bg-red-100 text-red-800"
                                      : "bg-gray-100 text-gray-800"
                                }`}
                              >
                                {exe.status}
                              </span>
                            </td>
                            <td className="p-2">{exe.solver_status || "-"}</td>
                            <td className="p-2 text-right font-mono">
                              {exe.objective_value?.toLocaleString(undefined, { maximumFractionDigits: 4 }) ?? "-"}
                            </td>
                            <td className="p-2 text-right">{formatMs(exe.execution_time_ms)}</td>
                            <td className="p-2 text-right">{exe.num_variables ?? "-"}</td>
                            <td className="p-2 text-right">{exe.num_constraints ?? "-"}</td>
                            <td className="p-2 text-right">
                              {exe.gap != null ? formatPct(exe.gap) : "-"}
                            </td>
                            <td className="p-2">
                              <OriginBadge origin={exe.origin} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {comparedMissingIds.length > 0 && (
                      <p className="text-xs text-muted-foreground mt-3">
                        {t("notFound", { ids: comparedMissingIds.join(", ") })}
                      </p>
                    )}
                  </div>
                ) : compareData ? (
                  <p className="text-muted-foreground text-sm text-center py-8">{t("noMatch")}</p>
                ) : compareIds.length === 0 ? (
                  <p className="text-muted-foreground text-sm text-center py-8">{t("noExecutions")}</p>
                ) : null}
              </div>
            </TabsContent>
          </Tabs>
        </>
      )}
    </div>
  );
}
