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

/**
 * A gap as a percentage, with enough digits to stay distinct.
 *
 * The axis spans decades, so a fixed number of decimals collapses the bottom of
 * it: 0.0005% and 0.00005% both render as "0.00%" and two ticks show the same
 * label on different lines.
 */
function percent(value: number): string {
  const pct = value * 100;
  if (pct === 0) return "0%";
  const digits = pct >= 1 ? 1 : Math.min(8, Math.ceil(-Math.log10(pct)) + 1);
  return `${pct.toLocaleString(undefined, { maximumFractionDigits: digits })}%`;
}

/**
 * How each solver closed its gap, on one clock.
 *
 * The gap is what is left between the answer a solver holds and the bound it has
 * proved. A line falling steeply had a good answer early; a line that runs flat
 * spent its time proving one it already had. A line reaching the bottom of the
 * axis closed the gap completely.
 *
 * Only solvers that report while they search appear. The others ran, and are
 * named underneath: a solver missing from a chart without a word reads as one
 * nobody asked for.
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

      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={series} margin={{ top: 8, right: 16, bottom: 48, left: 4 }}>
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
              offset: -14,
              style: AXIS_TICK,
            }}
          />
          {/* Logarithmic on purpose. The gap on a real instance runs from 100%
              to 0.0005%, and a linear axis puts every decade below the first one
              on the same pixel. */}
          <YAxis
            type="number"
            scale="log"
            domain={data.domain}
            allowDataOverflow
            tick={AXIS_TICK}
            tickFormatter={percent}
            width={78}
          />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            labelFormatter={(value) => seconds(Number(value))}
            formatter={(value, name) => [percent(Number(value)), String(name)]}
          />
          <Legend wrapperStyle={{ fontSize: 11, paddingTop: 20 }} verticalAlign="bottom" />
          {data.lines.map((line) => (
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
            />
          ))}
        </LineChart>
      </ResponsiveContainer>

      <div className="space-y-1 text-xs text-muted-foreground">
        {data.anyProved ? <p>{t("charts.convergenceFloor")}</p> : null}
        {data.silent.length > 0 ? (
          <p>{t("charts.convergenceSilent", { solvers: data.silent.join(", ") })}</p>
        ) : null}
      </div>
    </div>
  );
}
