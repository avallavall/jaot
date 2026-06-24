"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useTranslations } from "next-intl";
import type { TimeSeriesDataPoint } from "@/lib/types";

interface RevenueChartProps {
  data: TimeSeriesDataPoint[];
}

function formatDate(dateStr: unknown) {
  return new Date(String(dateStr)).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

export function RevenueChart({ data }: RevenueChartProps) {
  const t = useTranslations("seller.analytics");

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-medium">
          {t("revenueChart")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-8">
            {t("noData")}
          </p>
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
              <XAxis
                dataKey="date"
                tickFormatter={formatDate}
                fontSize={12}
                tickMargin={8}
              />
              <YAxis
                yAxisId="left"
                fontSize={12}
                tickMargin={4}
                label={{
                  value: t("views"),
                  angle: -90,
                  position: "insideLeft",
                  style: { fontSize: 12 },
                }}
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                fontSize={12}
                tickMargin={4}
                label={{
                  value: t("activations"),
                  angle: 90,
                  position: "insideRight",
                  style: { fontSize: 12 },
                }}
              />
              <Tooltip
                labelFormatter={formatDate}
                contentStyle={{
                  borderRadius: "8px",
                  border: "1px solid hsl(var(--border))",
                  backgroundColor: "hsl(var(--card))",
                }}
              />
              <Legend />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="views"
                stroke="#3b82f6"
                strokeWidth={2}
                dot={false}
                name={t("views")}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="activations"
                stroke="#22c55e"
                strokeWidth={2}
                dot={false}
                name={t("activations")}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
