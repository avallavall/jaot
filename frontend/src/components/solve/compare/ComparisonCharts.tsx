"use client";

import { useTranslations } from "next-intl";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ComparisonDetail } from "@/lib/types";
import { ConvergenceChart } from "./ConvergenceChart";
import { WorkChart } from "./WorkChart";
import {
  type BoundBar,
  type BoundOmission,
  type SplitBar,
  type TimeBar,
  boundBars,
  boundDomain,
  boundOmissions,
  logDomain,
  splitBars,
  timeBars,
} from "./comparison-charts";

/** Row height plus room for the axis. Four solvers must not need a scrollbar. */
function chartHeight(rows: number): number {
  return Math.max(120, rows * 34 + 44);
}

const AXIS_TICK = { fontSize: 11, fill: "var(--muted-foreground)" };
const SOLVER_AXIS_WIDTH = 62;

const TOOLTIP_STYLE = {
  backgroundColor: "var(--popover)",
  border: "1px solid var(--border)",
  borderRadius: "0.5rem",
  fontSize: 12,
  color: "var(--popover-foreground)",
};

function seconds(value: number): string {
  return `${value.toLocaleString(undefined, { maximumFractionDigits: value < 1 ? 3 : 2 })} s`;
}

/**
 * The three things the table states in numbers and cannot show.
 *
 * Each one is drawn only when there are at least two solvers with the data it
 * needs. A chart of one bar compares nothing, and a chart with a solver silently
 * missing is worse than no chart: the reader assumes everyone is in it.
 */
export function ComparisonCharts({ comparison }: { comparison: ComparisonDetail }) {
  const times = timeBars(comparison);
  const bounds = boundBars(comparison);
  const splits = splitBars(comparison);

  if (times.length === 0 && bounds.length === 0 && splits.length === 0) return null;

  return (
    <div className="space-y-6" data-testid="comparison-charts">
      {bounds.length > 0 ? (
        <BoundChart bars={bounds} omitted={boundOmissions(comparison)} />
      ) : null}
      {times.length > 0 ? <TimeChart bars={times} /> : null}
      {splits.length > 0 ? <SplitChart bars={splits} /> : null}
      {/* Draws itself only when two solvers reported while they searched, which
          today means SCIP and CBC. It says nothing the three bar charts say. */}
      <ConvergenceChart results={comparison.results} />
      {/* Last, because it answers the question the time chart raises: the time
          chart says who was slower, this says whether the tree was bigger or the
          nodes were dearer. */}
      <WorkChart results={comparison.results} />
    </div>
  );
}

/**
 * Objective to bound, one bar per solver on one shared axis.
 *
 * Drawn as an invisible offset plus the real segment — the standard way to put a
 * floating bar on a linear axis. A solver that proved its answer has nothing to
 * draw, so it gets a marker of a few pixels rather than disappearing.
 */
function BoundChart({ bars, omitted }: { bars: BoundBar[]; omitted: BoundOmission[] }) {
  const t = useTranslations("solverCompare");
  const [low, high] = boundDomain(bars);

  return (
    <figure data-testid="comparison-chart-bound">
      <figcaption className="mb-1 text-xs font-medium text-muted-foreground">
        {t("charts.boundTitle")}
      </figcaption>
      <div style={{ height: chartHeight(bars.length) }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={bars} layout="vertical" margin={{ top: 4, right: 20, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-border/50" horizontal={false} />
            <XAxis
              type="number"
              domain={[low, high]}
              // Without this a bar chart's axis is forced to include zero, and
              // the interesting stretch — the last few percent between bound and
              // answer — is squeezed into the right edge.
              allowDataOverflow
              tick={AXIS_TICK}
              tickFormatter={(value: number) =>
                value.toLocaleString(undefined, { maximumFractionDigits: 2 })
              }
            />
            <YAxis
              type="category"
              dataKey="solver"
              width={SOLVER_AXIS_WIDTH}
              tick={AXIS_TICK}
              tickFormatter={(name: string) => name.toUpperCase()}
            />
            <Tooltip
              cursor={{ fill: "var(--muted)", fillOpacity: 0.3 }}
              contentStyle={TOOLTIP_STYLE}
              formatter={(_value, _name, item) => {
                const bar = item.payload as BoundBar;
                return [
                  t("charts.boundTooltip", {
                    objective: bar.objective,
                    bound: bar.bound,
                    distance: bar.span,
                  }),
                  "",
                ];
              }}
              labelFormatter={(label) => String(label).toUpperCase()}
            />
            <Bar dataKey="low" stackId="bound" fill="transparent" isAnimationActive={false} />
            <Bar
              dataKey="span"
              stackId="bound"
              radius={2}
              minPointSize={3}
              isAnimationActive={false}
            >
              {bars.map((bar) => (
                <Cell
                  key={bar.solver}
                  // A proven answer is a point, not a distance: it gets the
                  // "settled" colour so an eye can sort them at a glance.
                  fill={bar.proven ? "var(--primary)" : "hsl(35, 85%, 55%)"}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{t("charts.boundLegend")}</p>
      {/* A solver missing from a chart reads as a solver that was never asked.
          The reason is per solver: one that answered and reported no bound is
          not the same as one that answered nothing. */}
      {omitted.length > 0 ? (
        <div className="text-xs text-muted-foreground" data-testid="comparison-chart-bound-omitted">
          {omitted.map((omission) => (
            <p key={omission.solver}>
              {t(`charts.boundOmitted.${omission.reason}`, {
                solver: omission.solver.toUpperCase(),
              })}
            </p>
          ))}
        </div>
      ) : null}
    </figure>
  );
}

/** Total time per solver, on a logarithmic axis. */
function TimeChart({ bars }: { bars: TimeBar[] }) {
  const t = useTranslations("solverCompare");
  const domain = logDomain(bars.map((bar) => bar.seconds));

  return (
    <figure data-testid="comparison-chart-time">
      <figcaption className="mb-1 text-xs font-medium text-muted-foreground">
        {t("charts.timeTitle")}
      </figcaption>
      <div style={{ height: chartHeight(bars.length) }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={bars} layout="vertical" margin={{ top: 4, right: 20, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-border/50" horizontal={false} />
            <XAxis
              type="number"
              scale="log"
              domain={domain}
              allowDataOverflow
              tick={AXIS_TICK}
              tickFormatter={(value: number) => seconds(value)}
            />
            <YAxis
              type="category"
              dataKey="solver"
              width={SOLVER_AXIS_WIDTH}
              tick={AXIS_TICK}
              tickFormatter={(name: string) => name.toUpperCase()}
            />
            <Tooltip
              cursor={{ fill: "var(--muted)", fillOpacity: 0.3 }}
              contentStyle={TOOLTIP_STYLE}
              formatter={(_value, _name, item) => {
                const bar = item.payload as TimeBar;
                return [
                  t("charts.timeTooltip", {
                    seconds: seconds(bar.seconds),
                    ratio: bar.ratio.toLocaleString(undefined, { maximumFractionDigits: 1 }),
                  }),
                  "",
                ];
              }}
              labelFormatter={(label) => String(label).toUpperCase()}
            />
            <Bar dataKey="seconds" radius={2} fill="var(--primary)" isAnimationActive={false}>
              {/* The number on the bar, because on a log axis the length alone
                  does not tell you how much longer one solver took. */}
              <LabelList
                dataKey="seconds"
                position="right"
                style={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                formatter={(value) => (typeof value === "number" ? seconds(value) : "")}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      {/* Said outright, because bar length on a log axis is NOT proportional to
          the number and a reader who assumes it is will read it wrong. */}
      <p className="mt-1 text-xs text-muted-foreground">{t("charts.timeLegend")}</p>
    </figure>
  );
}

/** Search time against the time spent building the solver's model. */
function SplitChart({ bars }: { bars: SplitBar[] }) {
  const t = useTranslations("solverCompare");

  return (
    <figure data-testid="comparison-chart-split">
      <figcaption className="mb-1 text-xs font-medium text-muted-foreground">
        {t("charts.splitTitle")}
      </figcaption>
      <div style={{ height: chartHeight(bars.length) }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={bars} layout="vertical" margin={{ top: 4, right: 20, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-border/50" horizontal={false} />
            <XAxis
              type="number"
              tick={AXIS_TICK}
              tickFormatter={(value: number) => seconds(value)}
            />
            <YAxis
              type="category"
              dataKey="solver"
              width={SOLVER_AXIS_WIDTH}
              tick={AXIS_TICK}
              tickFormatter={(name: string) => name.toUpperCase()}
            />
            <Tooltip
              cursor={{ fill: "var(--muted)", fillOpacity: 0.3 }}
              contentStyle={TOOLTIP_STYLE}
              formatter={(value, name) => [
                seconds(Number(value)),
                name === "search" ? t("charts.splitSearch") : t("charts.splitBuild"),
              ]}
              labelFormatter={(label) => String(label).toUpperCase()}
            />
            <Bar
              dataKey="search"
              stackId="split"
              fill="var(--primary)"
              radius={[2, 0, 0, 2]}
              isAnimationActive={false}
            />
            <Bar
              dataKey="build"
              stackId="split"
              fill="hsl(215, 20%, 65%)"
              radius={[0, 2, 2, 0]}
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{t("charts.splitLegend")}</p>
    </figure>
  );
}
