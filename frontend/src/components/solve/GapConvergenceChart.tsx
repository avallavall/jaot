"use client";

import React from "react";
import { useTranslations } from "next-intl";
import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

interface ProgressPoint {
  iteration: number;
  objective: number;
  gap: number;
  timestamp: number;
}

interface ChartDataPoint {
  iteration: number;
  primalBound: number;
  dualBound: number;
  gapPercent: string;
}

interface GapConvergenceChartProps {
  progressHistory: ProgressPoint[];
  objectiveSense?: "minimize" | "maximize";
  chartRef?: React.RefObject<HTMLDivElement | null>;
}

export function GapConvergenceChart({
  progressHistory,
  objectiveSense = "minimize",
  chartRef,
}: GapConvergenceChartProps) {
  const t = useTranslations("solve.charts.gapConvergence");
  if (progressHistory.length === 0) {
    return (
      <div
        ref={chartRef}
        className="flex items-center justify-center h-32 border border-border rounded-lg bg-muted/20"
      >
        <p className="text-sm text-muted-foreground text-center px-4">
          {t("noData")}
        </p>
      </div>
    );
  }
  // Single-point fallback: show a metrics card instead of an empty chart.
  if (progressHistory.length < 2) {
    const only = progressHistory[0];
    const dual =
      objectiveSense === "minimize"
        ? only.objective * (1 - only.gap)
        : only.objective * (1 + only.gap);
    const fmt = (v: number) =>
      v.toLocaleString(undefined, { maximumFractionDigits: 6 });
    return (
      <div
        ref={chartRef}
        className="grid grid-cols-3 gap-4 border border-border rounded-lg bg-muted/20 p-4"
      >
        <MetricCell label={t("primalBound")} value={fmt(only.objective)} emphasised />
        <MetricCell
          label={t("dualBound")}
          value={Number.isFinite(dual) ? fmt(dual) : "—"}
        />
        <MetricCell label={t("gapLabel")} value={`${(only.gap * 100).toFixed(4)}%`} />
      </div>
    );
  }

  const chartData: ChartDataPoint[] = progressHistory.map((p) => {
    const primalBound = p.objective;
    const dualBound =
      objectiveSense === "minimize"
        ? primalBound * (1 - p.gap)
        : primalBound * (1 + p.gap);
    return {
      iteration: p.iteration,
      primalBound,
      dualBound,
      gapPercent: (p.gap * 100).toFixed(1),
    };
  });

  const lastPoint = chartData[chartData.length - 1];
  const currentGap = lastPoint ? parseFloat(lastPoint.gapPercent) : null;

  return (
    <div ref={chartRef}>
      <ResponsiveContainer width="100%" height={220}>
        <ComposedChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis
            dataKey="iteration"
            tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
            label={{
              value: t("iteration"),
              position: "insideBottomRight",
              offset: -10,
              fontSize: 11,
              fill: "var(--muted-foreground)",
            }}
          />
          <YAxis
            tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
            width={60}
            tickFormatter={(v: number) =>
              v.toLocaleString(undefined, { maximumFractionDigits: 4, notation: "compact" } as Intl.NumberFormatOptions)
            }
          />
          <Tooltip
            contentStyle={{
              background: "var(--card)",
              border: "1px solid var(--border)",
              borderRadius: "4px",
              fontSize: 12,
            }}
            labelStyle={{ color: "var(--foreground)", fontWeight: 600, marginBottom: 4 }}
            labelFormatter={(label) => `${t("iteration")} ${label}`}
            formatter={(value: number | string | undefined) =>
              typeof value === "number"
                ? value.toLocaleString(undefined, { maximumFractionDigits: 6 })
                : String(value ?? "")
            }
          />
          <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
          <Line
            type="monotone"
            dataKey="primalBound"
            name={t("primalBound")}
            stroke="var(--primary)"
            strokeWidth={2}
            dot={false}
            animationDuration={300}
          />
          <Line
            type="monotone"
            dataKey="dualBound"
            name={t("dualBound")}
            stroke="var(--muted-foreground)"
            strokeWidth={2}
            dot={false}
            strokeDasharray="4 2"
            animationDuration={300}
          />
        </ComposedChart>
      </ResponsiveContainer>

      {currentGap !== null && (
        <div className="mt-2 flex justify-end">
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-muted text-muted-foreground border border-border">
            {t("gap", { percent: currentGap })}
          </span>
        </div>
      )}
    </div>
  );
}

interface MetricCellProps {
  label: string;
  value: string;
  emphasised?: boolean;
}

function MetricCell({ label, value, emphasised = false }: MetricCellProps) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div
        className={`text-lg font-semibold mt-1 font-mono ${
          emphasised ? "text-primary" : "text-foreground"
        }`}
      >
        {value}
      </div>
    </div>
  );
}
