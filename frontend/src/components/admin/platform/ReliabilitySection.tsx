"use client";

import { useTranslations } from "next-intl";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PlatformKpiCard } from "./PlatformKpiCard";
import {
  CHART_COLORS,
  TOOLTIP_STYLE,
  fmtInt,
  fmtMs,
  fmtPct,
  fmtSeconds,
} from "./platform-helpers";
import type { Reliability } from "./platform-types";

export function ReliabilitySection({ data }: { data: Reliability }) {
  const t = useTranslations("admin.platformAnalytics");
  const a = data.automation;

  const failureData = Object.entries(data.failures_by_solver_status).map(([name, value]) => ({
    name,
    value,
  }));

  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold">{t("reliability.title")}</h2>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <PlatformKpiCard label={t("reliability.p50")} value={fmtMs(data.percentiles_ms.p50)} />
        <PlatformKpiCard label={t("reliability.p95")} value={fmtMs(data.percentiles_ms.p95)} />
        <PlatformKpiCard label={t("reliability.p99")} value={fmtMs(data.percentiles_ms.p99)} />
        <PlatformKpiCard label={t("reliability.timeoutRate")} value={fmtPct(data.timeout_rate)} />
        <PlatformKpiCard label={t("reliability.failureRate")} value={fmtPct(data.failure_rate)} />
        <PlatformKpiCard
          label={t("reliability.queueTime")}
          value={fmtSeconds(data.avg_queue_time_s)}
        />
        <PlatformKpiCard label={t("reliability.asyncRuns")} value={fmtInt(data.async_count)} />
        <PlatformKpiCard label={t("reliability.syncRuns")} value={fmtInt(data.sync_count)} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">{t("reliability.failuresByReason")}</CardTitle>
          </CardHeader>
          <CardContent>
            {failureData.length === 0 ? (
              <p className="py-12 text-center text-sm text-muted-foreground">{t("noData")}</p>
            ) : (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={failureData} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                  <XAxis type="number" tick={{ fontSize: 11 }} allowDecimals={false} />
                  <YAxis
                    type="category"
                    dataKey="name"
                    tick={{ fontSize: 11 }}
                    width={110}
                  />
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                  <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                    {failureData.map((_, i) => (
                      <Cell key={i} fill={CHART_COLORS[(i + 2) % CHART_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">{t("reliability.automation")}</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-3">
            <PlatformKpiCard label={t("reliability.triggers")} value={fmtInt(a.total_triggers)} />
            <PlatformKpiCard
              label={t("reliability.activeTriggers")}
              value={fmtInt(a.active_triggers)}
            />
            <PlatformKpiCard label={t("reliability.totalRuns")} value={fmtInt(a.total_runs)} />
            <PlatformKpiCard
              label={t("reliability.cronSuccess")}
              value={fmtPct(a.cron_success_rate)}
            />
            <PlatformKpiCard
              label={t("reliability.webhookDelivery")}
              value={fmtPct(a.webhook_delivery_rate)}
            />
            <PlatformKpiCard
              label={t("reliability.schedulesFailing")}
              value={fmtInt(a.schedules_failing)}
            />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">{t("reliability.lowSuccessModels")}</CardTitle>
        </CardHeader>
        <CardContent>
          {data.low_success_models.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">{t("noData")}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="py-2 pr-4 font-medium">{t("reliability.model")}</th>
                    <th className="py-2 pr-4 font-medium">{t("health.category")}</th>
                    <th className="py-2 pr-4 text-right font-medium">{t("health.successRate")}</th>
                    <th className="py-2 text-right font-medium">{t("health.executions")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.low_success_models.map((m) => (
                    <tr key={m.id} className="border-b border-border/50">
                      <td className="py-2 pr-4">{m.display_name}</td>
                      <td className="py-2 pr-4 text-muted-foreground">{m.category}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">
                        {fmtPct(m.success_rate)}
                      </td>
                      <td className="py-2 text-right tabular-nums">{fmtInt(m.total_executions)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </section>
  );
}
