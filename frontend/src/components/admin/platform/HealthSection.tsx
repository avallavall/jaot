"use client";

import { useTranslations } from "next-intl";
import {
  ResponsiveContainer,
  LineChart,
  Line,
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
  fmtNum,
  fmtPct,
  fmtMs,
} from "./platform-helpers";
import type { PlatformOverview } from "./platform-types";

export function HealthSection({ data }: { data: PlatformOverview }) {
  const t = useTranslations("admin.platformAnalytics");
  const e = data.executions;

  const planData = Object.entries(data.plan_distribution).map(([name, value]) => ({
    name,
    value,
  }));
  const dailyData = data.daily.map((d) => ({ label: d.date.slice(5), executions: d.executions }));

  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold">{t("health.title")}</h2>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <PlatformKpiCard
          label={t("health.users")}
          value={fmtInt(data.users.total)}
          hint={t("health.newInPeriod", { count: data.users.new })}
        />
        <PlatformKpiCard label={t("health.activeUsers")} value={fmtInt(data.users.active)} />
        <PlatformKpiCard
          label={t("health.organizations")}
          value={fmtInt(data.orgs.total)}
          hint={t("health.newInPeriod", { count: data.orgs.new })}
        />
        <PlatformKpiCard
          label={t("health.avgUsersPerOrg")}
          value={fmtNum(data.avg_users_per_org)}
        />
        <PlatformKpiCard label={t("health.totalExecutions")} value={fmtInt(e.total)} />
        <PlatformKpiCard label={t("health.execPerUser")} value={fmtNum(e.per_user)} />
        <PlatformKpiCard label={t("health.execPerOrg")} value={fmtNum(e.per_org)} />
        <PlatformKpiCard label={t("health.successRate")} value={fmtPct(e.success_rate)} />
        <PlatformKpiCard label={t("health.avgSolveTime")} value={fmtMs(e.avg_solve_time_ms)} />
        <PlatformKpiCard
          label={t("health.medianSolveTime")}
          value={fmtMs(e.median_solve_time_ms)}
        />
        <PlatformKpiCard
          label={t("health.builderSolves")}
          value={fmtInt(data.builder_solves.total)}
          hint={`${fmtPct(data.builder_solves.success_rate)} · ${fmtMs(
            data.builder_solves.avg_solve_time_ms,
          )}`}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">{t("health.dailyExecutions")}</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={dailyData}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Line
                  type="monotone"
                  dataKey="executions"
                  stroke={CHART_COLORS[0]}
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">{t("health.planMix")}</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={planData}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {planData.map((_, i) => (
                    <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">{t("health.byCategory")}</CardTitle>
        </CardHeader>
        <CardContent>
          {data.by_category.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">{t("noData")}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="py-2 pr-4 font-medium">{t("health.category")}</th>
                    <th className="py-2 pr-4 text-right font-medium">{t("health.executions")}</th>
                    <th className="py-2 pr-4 text-right font-medium">{t("health.avgTime")}</th>
                    <th className="py-2 text-right font-medium">{t("health.successRate")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_category.map((row) => (
                    <tr key={row.category} className="border-b border-border/50">
                      <td className="py-2 pr-4">{row.category}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">
                        {fmtInt(row.executions)}
                      </td>
                      <td className="py-2 pr-4 text-right tabular-nums">
                        {fmtMs(row.avg_solve_time_ms)}
                      </td>
                      <td className="py-2 text-right tabular-nums">{fmtPct(row.success_rate)}</td>
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
