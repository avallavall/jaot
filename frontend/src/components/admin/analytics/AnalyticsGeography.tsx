"use client";

import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
} from "recharts";
import { Globe } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CountryEntry } from "./analytics-types";
import { TOOLTIP_STYLE } from "./analytics-helpers";

interface AnalyticsGeographyProps {
  countries: CountryEntry[];
  onCountryClick?: (code: string) => void;
}

export function AnalyticsGeography({
  countries,
  onCountryClick,
}: AnalyticsGeographyProps) {
  const top10 = countries.slice(0, 10);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Globe className="h-4 w-4" />
          Top Countries
        </CardTitle>
      </CardHeader>
      <CardContent>
        {top10.length > 0 ? (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={top10} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
              <XAxis type="number" tick={{ fontSize: 12 }} />
              <YAxis
                type="category"
                dataKey="country_code"
                width={40}
                tick={{ fontSize: 12, fontWeight: 600 }}
              />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Bar
                dataKey="count"
                radius={[0, 4, 4, 0]}
                fill="#3b82f6"
                onClick={(_data: unknown, index: number) => {
                  const entry = top10[index];
                  if (entry) onCountryClick?.(entry.country_code);
                }}
                className="cursor-pointer"
              >
                {top10.map((_, index) => (
                  <Cell
                    key={`country-${index}`}
                    fill={
                      index === 0
                        ? "#3b82f6"
                        : index < 3
                          ? "#60a5fa"
                          : "#93c5fd"
                    }
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-center text-muted-foreground py-12">
            No events recorded yet
          </p>
        )}
      </CardContent>
    </Card>
  );
}
