"use client";

import { useMemo } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { VariableSolution } from "@/lib/types";
import { useTranslations } from "next-intl";

interface VariableValuesChartProps {
  variables: VariableSolution[];
}

const TYPE_COLORS: Record<string, string> = {
  continuous: "#6366f1", // indigo
  integer: "#f59e0b", // amber
  binary: "#10b981", // emerald
};

function getColor(type: string): string {
  return TYPE_COLORS[type] || "#94a3b8";
}

export function VariableValuesChart({ variables }: VariableValuesChartProps) {
  const t = useTranslations("solve.visualization");

  const { data, hasTruncated } = useMemo(() => {
    const sorted = [...variables].sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
    return {
      data: sorted.slice(0, 40).map((v) => ({ name: v.name, value: v.value, type: v.type })),
      hasTruncated: variables.length > 40,
    };
  }, [variables]);

  if (variables.length === 0) return null;

  // Horizontal layout: variable names live on the Y-axis where there is room,
  // instead of overlapping on a crammed X-axis (long generated names like
  // "f_industrial_district_advanced_plant_..." were unreadable). Height scales
  // with the bar count and the chart scrolls vertically past a threshold.
  const chartHeight = Math.max(300, data.length * 26 + 40);

  return (
    <div>
      <div className="overflow-y-auto" style={{ maxHeight: 520 }}>
        <div style={{ height: chartHeight }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={data}
              layout="vertical"
              margin={{ top: 5, right: 24, left: 8, bottom: 5 }}
            >
              <XAxis
                type="number"
                tick={{ fontSize: 11 }}
                tickFormatter={(v: number) =>
                  v.toLocaleString(undefined, { maximumFractionDigits: 2 })
                }
              />
              <YAxis
                type="category"
                dataKey="name"
                width={180}
                interval={0}
                tick={{ fontSize: 11 }}
                tickFormatter={(name: string) =>
                  name.length > 26 ? `${name.slice(0, 24)}…` : name
                }
              />
              <Tooltip
                labelFormatter={(label) => String(label ?? "")}
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                formatter={(value: any) =>
                  typeof value === "number"
                    ? value.toLocaleString(undefined, { maximumFractionDigits: 6 })
                    : String(value ?? "")
                }
              />
              <Bar dataKey="value" radius={[0, 2, 2, 0]}>
                {data.map((entry, i) => (
                  <Cell key={i} fill={getColor(entry.type)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
      {hasTruncated && (
        <p className="text-xs text-muted-foreground mt-2 text-center">
          {t("showingTop", { count: 40, total: variables.length })}
        </p>
      )}
    </div>
  );
}
