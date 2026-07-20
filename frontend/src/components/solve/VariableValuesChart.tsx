"use client";

import { useMemo, useState } from "react";
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

const NEAR_ZERO = 1e-9;

export function VariableValuesChart({ variables }: VariableValuesChartProps) {
  const t = useTranslations("solve.visualization");
  // When the chart carries no information (all bars identical) we collapse to an
  // aggregate; this lets the user force the chart anyway.
  const [forceChart, setForceChart] = useState(false);

  const { data, hasTruncated, zerosHidden, nonZeroCount, uninformative, commonValue } = useMemo(
    () => {
      // A zero-length bar is invisible — rows for zero variables are pure noise
      // in a magnitude chart, so they are always excluded (with a note below).
      const nonZero = variables.filter((v) => Math.abs(v.value) > NEAR_ZERO);
      const sorted = [...nonZero].sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
      // Min/max magnitude via reduce (not spread — the array can be thousands long).
      let min = Infinity;
      let max = -Infinity;
      for (const v of nonZero) {
        const m = Math.abs(v.value);
        if (m < min) min = m;
        if (m > max) max = m;
      }
      // A binary assignment/routing solution is dozens-to-hundreds of bars all at
      // 1.0 — identical length, zero information. Detect the degenerate "every
      // non-zero variable is the same magnitude" case and collapse it.
      const uninformative = nonZero.length >= 3 && max - min < NEAR_ZERO;
      return {
        data: sorted.slice(0, 40).map((v) => ({ name: v.name, value: v.value, type: v.type })),
        hasTruncated: nonZero.length > 40,
        zerosHidden: variables.length - nonZero.length,
        nonZeroCount: nonZero.length,
        uninformative,
        commonValue: nonZero.length > 0 ? nonZero[0].value : 0,
      };
    },
    [variables],
  );

  if (variables.length === 0) return null;

  const valueStr = commonValue.toLocaleString(undefined, { maximumFractionDigits: 6 });

  if (uninformative && !forceChart) {
    return (
      <div className="space-y-4" data-testid="variable-values-aggregate">
        <p className="text-sm text-muted-foreground">{t("chartAllSame", { value: valueStr })}</p>
        <div className="grid grid-cols-2 gap-3">
          <Stat value={nonZeroCount} label={t("aggregateAtValue", { value: valueStr })} />
          <Stat value={zerosHidden} label={t("aggregateAtZero")} />
        </div>
        <button
          type="button"
          onClick={() => setForceChart(true)}
          data-testid="variable-values-show-chart"
          className="text-xs font-medium text-primary hover:underline"
        >
          {t("showChartAnyway")}
        </button>
      </div>
    );
  }

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
      {(hasTruncated || zerosHidden > 0) && (
        <p className="text-xs text-muted-foreground mt-2 text-center">
          {hasTruncated && t("showingTop", { count: 40, total: nonZeroCount })}
          {hasTruncated && zerosHidden > 0 && " · "}
          {zerosHidden > 0 && t("zerosHidden", { count: zerosHidden })}
        </p>
      )}
    </div>
  );
}

function Stat({ value, label }: { value: number; label: string }) {
  return (
    <div className="rounded-lg border border-border bg-muted/30 p-3 text-center">
      <div className="font-mono text-2xl font-semibold text-foreground tabular-nums">
        {value.toLocaleString()}
      </div>
      <div className="mt-0.5 text-xs text-muted-foreground">{label}</div>
    </div>
  );
}
