"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useTranslations } from "next-intl";
import type { GeoDistributionEntry } from "@/lib/types";

interface GeoDistributionProps {
  data: GeoDistributionEntry[];
}

export function GeoDistribution({ data }: GeoDistributionProps) {
  const t = useTranslations("seller.analytics");

  // Top 10 countries, sorted by count descending
  const top10 = [...data]
    .sort((a, b) => b.count - a.count)
    .slice(0, 10);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-medium">
          {t("geoDistribution")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {top10.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-8">
            {t("noData")}
          </p>
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={top10} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
              <XAxis type="number" fontSize={12} />
              <YAxis
                dataKey="country"
                type="category"
                width={40}
                fontSize={12}
              />
              <Tooltip
                contentStyle={{
                  borderRadius: "8px",
                  border: "1px solid hsl(var(--border))",
                  backgroundColor: "hsl(var(--card))",
                }}
                formatter={(value) => [Number(value).toLocaleString(), t("viewCount")]}
              />
              <Bar
                dataKey="count"
                fill="#6366f1"
                radius={[0, 4, 4, 0]}
                name={t("viewCount")}
              />
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
