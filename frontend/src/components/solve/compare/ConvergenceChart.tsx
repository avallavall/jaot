"use client";

import { useTranslations } from "next-intl";
import { useMemo } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ComparisonSolverResult } from "@/lib/types";

import { convergenceData, convergenceSeries } from "./convergence";

/** Five tokens, five solvers, in the order the comparison ran them. */
const CHART_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

const AXIS_TICK = { fontSize: 11, fill: "var(--muted-foreground)" };

const TOOLTIP_STYLE = {
  backgroundColor: "var(--popover)",
  border: "1px solid var(--border)",
  borderRadius: "0.5rem",
  fontSize: 12,
  color: "var(--popover-foreground)",
};

function seconds(value: number): string {
  return `${value.toLocaleString(undefined, { maximumFractionDigits: value < 1 ? 2 : 1 })} s`;
}

function number(value: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

/**
 * How each solver closed the gap, on one clock.
 *
 * The solid line is the best answer the solver held at that instant; the dashed
 * line of the same colour is the bound it had proved. Where they meet, the
 * search is over.
 *
 * Only solvers that report while they search appear. The others ran and are
 * named underneath, because a solver missing from a chart without a word reads
 * as one nobody asked for.
 */
export function ConvergenceChart({ results }: { results: ComparisonSolverResult[] }) {
  const t = useTranslations("solverCompare");

  const data = useMemo(() => convergenceData(results), [results]);
  const series = useMemo(() => (data ? convergenceSeries(data) : []), [data]);

  if (!data) return null;

  const order = results.map((r) => r.solver_name);
  const colorOf = (solver: string) => CHART_COLORS[order.indexOf(solver) % CHART_COLORS.length];

  return (
    <div className="space-y-2" data-testid="convergence-chart">
      <div>
        <h4 className="text-sm font-medium">{t("charts.convergenceTitle")}</h4>
        <p className="text-xs text-muted-foreground">{t("charts.convergenceLegend")}</p>
      </div>

      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={series} margin={{ top: 8, right: 16, bottom: 24, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis
            dataKey="seconds"
            type="number"
            domain={[0, data.maxSeconds]}
            tick={AXIS_TICK}
            tickFormatter={seconds}
            label={{
              value: t("charts.convergenceXAxis"),
              position: "insideBottom",
              offset: -12,
              style: AXIS_TICK,
            }}
          />
          <YAxis type="number" domain={["auto", "auto"]} tick={AXIS_TICK} width={64} />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            labelFormatter={(value) => seconds(Number(value))}
            formatter={(value, name) => [number(Number(value)), String(name)]}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {data.lines.map((line) => [
            <Line
              key={line.solver}
              type="stepAfter"
              dataKey={line.solver}
              name={line.solver}
              stroke={colorOf(line.solver)}
              strokeWidth={2}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />,
            <Line
              key={`${line.solver}__bound`}
              type="stepAfter"
              dataKey={`${line.solver}__bound`}
              name={t("charts.convergenceBoundOf", { solver: line.solver })}
              stroke={colorOf(line.solver)}
              strokeWidth={1.5}
              strokeDasharray="4 3"
              dot={false}
              connectNulls
              isAnimationActive={false}
            />,
          ])}
        </LineChart>
      </ResponsiveContainer>

      {data.silent.length > 0 ? (
        <p className="text-xs text-muted-foreground">
          {t("charts.convergenceSilent", { solvers: data.silent.join(", ") })}
        </p>
      ) : null}
    </div>
  );
}
