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

  return (
    <div>
      <div className="h-[300px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
            <XAxis
              dataKey="name"
              tick={{ fontSize: 11 }}
              interval={0}
              angle={data.length > 15 ? -45 : 0}
              textAnchor={data.length > 15 ? "end" : "middle"}
              height={data.length > 15 ? 80 : 30}
            />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              formatter={(value: any) =>
                typeof value === "number"
                  ? value.toLocaleString(undefined, { maximumFractionDigits: 6 })
                  : String(value ?? "")
              }
            />
            <Bar dataKey="value" radius={[2, 2, 0, 0]}>
              {data.map((entry, i) => (
                <Cell key={i} fill={getColor(entry.type)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      {hasTruncated && (
        <p className="text-xs text-muted-foreground mt-2 text-center">
          {t("showingTop", { count: 40, total: variables.length })}
        </p>
      )}
    </div>
  );
}
