"use client";

import { useEffect, useState, useMemo } from "react";
import { api, CreditTransaction, OrganizationModel } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { useTranslations } from "next-intl";
import { TrendingUp, Zap, Coins, Activity } from "lucide-react";

interface DailyCredit {
  date: string;
  credits: number;
}

interface DailyExecution {
  date: string;
  executions: number;
  failed: number;
}

interface TopModel {
  name: string;
  runs: number;
  credits: number;
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function groupByDay<T extends { created_at: string }>(items: T[], days: number) {
  const now = Date.now();
  const cutoff = now - days * 86400000;
  const map: Record<string, T[]> = {};

  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now - i * 86400000);
    const key = d.toISOString().slice(0, 10);
    map[key] = [];
  }

  for (const item of items) {
    const ts = new Date(item.created_at).getTime();
    if (ts < cutoff) continue;
    const key = new Date(item.created_at).toISOString().slice(0, 10);
    if (map[key]) map[key].push(item);
  }

  return map;
}

export default function UsagePage() {
  const t = useTranslations("workspace.usage");
  const [transactions, setTransactions] = useState<CreditTransaction[]>([]);
  const [models, setModels] = useState<OrganizationModel[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const [txData, modelData] = await Promise.all([
          api.getCreditTransactions({ limit: 100 }),
          api.getMyModels({ page_size: 50 }),
        ]);
        setTransactions(Array.isArray(txData) ? txData : (txData as { items?: CreditTransaction[] }).items ?? []);
        setModels(modelData.items);
      } catch (err) {
        console.warn('Failed to load usage data:', err);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  const creditsByDay: DailyCredit[] = useMemo(() => {
    const consumptions = transactions.filter(
      (t) => t.transaction_type === "execution_charge" || t.credits_amount < 0
    );
    const grouped = groupByDay(consumptions, 30);
    return Object.entries(grouped).map(([date, items]) => ({
      date: formatDate(date),
      credits: Math.abs(items.reduce((sum, t) => sum + t.credits_amount, 0)),
    }));
  }, [transactions]);

  const executionsByDay: DailyExecution[] = useMemo(() => {
    const execs = transactions.filter((t) => t.transaction_type === "execution_charge");
    const grouped = groupByDay(execs, 14);
    return Object.entries(grouped).map(([date, items]) => ({
      date: formatDate(date),
      executions: items.length,
      failed: 0,
    }));
  }, [transactions]);

  const topModels: TopModel[] = useMemo(() => {
    return [...models]
      .sort((a, b) => b.total_executions - a.total_executions)
      .slice(0, 5)
      .map((m) => ({
        name: m.display_name,
        runs: m.total_executions,
        credits: m.total_credits_used,
      }));
  }, [models]);

  const totalCreditsUsed = useMemo(() =>
    transactions.filter((t) => t.credits_amount < 0)
      .reduce((sum, t) => sum + Math.abs(t.credits_amount), 0),
    [transactions]
  );

  const totalExecutions = useMemo(() =>
    models.reduce((sum, m) => sum + m.total_executions, 0),
    [models]
  );

  const activeModels = models.filter((m) => m.is_active).length;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-serif text-foreground mb-1">{t("title")}</h1>
        <p className="text-muted-foreground">{t("subtitle")}</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <SummaryCard
          icon={<Coins className="w-5 h-5" />}
          label={t("creditsUsedAllTime")}
          value={loading ? null : totalCreditsUsed.toLocaleString()}
        />
        <SummaryCard
          icon={<Activity className="w-5 h-5" />}
          label={t("totalExecutions")}
          value={loading ? null : totalExecutions.toLocaleString()}
        />
        <SummaryCard
          icon={<Zap className="w-5 h-5" />}
          label={t("activeModels")}
          value={loading ? null : String(activeModels)}
        />
      </div>

      {/* Credit usage line chart — 30 days */}
      <Card className="border-border">
        <CardHeader>
          <CardTitle className="text-lg font-serif flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-primary" />
            {t("creditUsage30Days")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <Skeleton className="h-56 w-full" />
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={creditsByDay} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                  interval={4}
                />
                <YAxis tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} width={40} />
                <Tooltip
                  contentStyle={{
                    background: "var(--card)",
                    border: "1px solid var(--border)",
                    borderRadius: "0",
                    fontSize: 12,
                  }}
                  labelStyle={{ color: "var(--foreground)" }}
                />
                <Line
                  type="monotone"
                  dataKey="credits"
                  stroke="var(--primary)"
                  strokeWidth={2}
                  dot={false}
                  name={t("creditsUsed")}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      {/* Executions bar chart — 14 days */}
      <Card className="border-border">
        <CardHeader>
          <CardTitle className="text-lg font-serif flex items-center gap-2">
            <Activity className="w-5 h-5 text-primary" />
            {t("executions14Days")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <Skeleton className="h-56 w-full" />
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={executionsByDay} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                  interval={1}
                />
                <YAxis tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} width={40} allowDecimals={false} />
                <Tooltip
                  contentStyle={{
                    background: "var(--card)",
                    border: "1px solid var(--border)",
                    borderRadius: "0",
                    fontSize: 12,
                  }}
                  labelStyle={{ color: "var(--foreground)" }}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="executions" fill="var(--primary)" name={t("executionsLabel")} radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      <Card className="border-border">
        <CardHeader>
          <CardTitle className="text-lg font-serif flex items-center gap-2">
            <Zap className="w-5 h-5 text-primary" />
            {t("topModels")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => <Skeleton key={i} className="h-10 w-full" />)}
            </div>
          ) : topModels.length === 0 ? (
            <p className="text-muted-foreground text-sm py-4 text-center">{t("noModelsUsed")}</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left py-2 font-medium text-muted-foreground">{t("modelColumn")}</th>
                  <th className="text-right py-2 font-medium text-muted-foreground">{t("runsColumn")}</th>
                  <th className="text-right py-2 font-medium text-muted-foreground">{t("creditsUsedColumn")}</th>
                </tr>
              </thead>
              <tbody>
                {topModels.map((m, i) => (
                  <tr key={m.name} className="border-b border-border last:border-0">
                    <td className="py-3 flex items-center gap-2">
                      <Badge variant="outline" className="text-xs w-5 h-5 p-0 flex items-center justify-center">
                        {i + 1}
                      </Badge>
                      <span className="font-medium truncate max-w-xs">{m.name}</span>
                    </td>
                    <td className="py-3 text-right">{m.runs.toLocaleString()}</td>
                    <td className="py-3 text-right">{m.credits.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function SummaryCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string | null;
}) {
  return (
    <Card className="border-border">
      <CardContent className="pt-5">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-md bg-primary/10 flex items-center justify-center text-primary flex-shrink-0">
            {icon}
          </div>
          <div>
            <p className="text-xs text-muted-foreground">{label}</p>
            {value === null ? (
              <Skeleton className="h-6 w-20 mt-1" />
            ) : (
              <p className="text-xl font-semibold">{value}</p>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
