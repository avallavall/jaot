"use client";

import { useTranslations } from "next-intl";
import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ComparisonSolverResult } from "@/lib/types";

import { type WorkPanel, workData } from "./work";

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

/** The plot area of one panel. The last panel is taller because it carries the
 * shared axis for all of them. */
const PANEL_HEIGHT = 88;
const AXIS_HEIGHT = 30;

function seconds(value: number): string {
  return `${value.toLocaleString(undefined, { maximumFractionDigits: value < 1 ? 2 : 1 })} s`;
}

/** Node counts reach the millions, and a full number on a 54px axis wraps. */
function compact(value: number): string {
  return value.toLocaleString(undefined, { notation: "compact", maximumFractionDigits: 1 });
}

function whole(value: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

/**
 * How much searching each solver did, one panel each.
 *
 * The time chart says who was slower. This says why: a solver can lose because
 * it explored far more of the tree, or because each piece of tree cost it more.
 * The count and the seconds together separate those two.
 *
 * Each panel keeps its own vertical scale on purpose. A node in one solver is
 * not a node in another — different presolve, different cuts, a different tree —
 * so the heights are not there to be compared. The clock is, and every panel
 * shares it.
 */
export function WorkChart({ results }: { results: ComparisonSolverResult[] }) {
  const t = useTranslations("solverCompare");

  const data = useMemo(() => workData({ results }), [results]);

  if (!data) return null;

  const order = results.map((row) => row.solver_name);
  const colorOf = (solver: string) => CHART_COLORS[order.indexOf(solver) % CHART_COLORS.length];

  return (
    <div className="space-y-2" data-testid="work-chart">
      <div>
        <h4 className="text-sm font-medium">{t("charts.workTitle")}</h4>
        <p className="text-xs text-muted-foreground">{t("charts.workLegend")}</p>
      </div>

      <div className="space-y-1">
        {data.panels.map((panel, index) => (
          <WorkPanelRow
            key={panel.solver}
            panel={panel}
            maxSeconds={data.maxSeconds}
            color={colorOf(panel.solver)}
            showAxis={index === data.panels.length - 1}
          />
        ))}
      </div>

      <div className="space-y-1 text-xs text-muted-foreground">
        {data.anyEndOnly ? <p>{t("charts.workEndOnly")}</p> : null}
        {data.omitted.map((omission) => (
          <p key={omission.solver}>
            {t(`charts.workOmitted.${omission.reason}`, {
              solver: omission.solver.toUpperCase(),
            })}
          </p>
        ))}
      </div>
    </div>
  );
}

/**
 * One solver's panel: its headline numbers, then its search against the clock.
 *
 * A solver that traced its search gets a line. One that reported only its final
 * count gets a single dot at the second it finished, which is everything it
 * said. The dot is explained in words under the chart, because a panel with one
 * mark next to a panel with a curve otherwise reads as a chart that failed.
 */
function WorkPanelRow({
  panel,
  maxSeconds,
  color,
  showAxis,
}: {
  panel: WorkPanel;
  maxSeconds: number;
  color: string;
  showAxis: boolean;
}) {
  const t = useTranslations("solverCompare");
  const unit = t(`charts.workUnit.${panel.unit}`);
  const points =
    panel.points.length > 0 ? panel.points : [{ seconds: panel.seconds, work: panel.total }];

  return (
    <figure data-testid={`work-panel-${panel.solver}`}>
      <figcaption className="flex flex-wrap items-baseline gap-x-2 text-xs">
        <span className="font-medium">{panel.solver.toUpperCase()}</span>
        <span className="text-muted-foreground">
          {t("charts.workSummary", {
            work: whole(panel.total),
            unit,
            seconds: seconds(panel.seconds),
            rate: whole(panel.perSecond),
          })}
        </span>
      </figcaption>
      <ResponsiveContainer width="100%" height={PANEL_HEIGHT + (showAxis ? AXIS_HEIGHT : 0)}>
        <LineChart data={points} margin={{ top: 6, right: 16, bottom: showAxis ? 20 : 4, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis
            dataKey="seconds"
            type="number"
            // Shared across every panel, so the panels line up in time. `hide`
            // keeps the scale and only drops the ticks, which is why the axis is
            // drawn once at the bottom instead of four times.
            domain={[0, maxSeconds]}
            hide={!showAxis}
            tick={AXIS_TICK}
            tickFormatter={seconds}
            label={
              showAxis
                ? {
                    value: t("charts.workXAxis"),
                    position: "insideBottom",
                    offset: -12,
                    style: AXIS_TICK,
                  }
                : undefined
            }
          />
          {/* Its own scale, never shared. See the note under the title. */}
          <YAxis
            type="number"
            domain={[0, "dataMax"]}
            allowDecimals={false}
            tick={AXIS_TICK}
            tickFormatter={compact}
            width={54}
          />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            labelFormatter={(value) => seconds(Number(value))}
            formatter={(value) => [`${whole(Number(value))} ${unit}`, panel.solver.toUpperCase()]}
          />
          {/* Straight segments, not a smoothed curve: nothing is known about
              what the solver did between two reports, and a spline would draw a
              shape it invented — including counts above the next point. */}
          <Line
            type="linear"
            dataKey="work"
            stroke={color}
            strokeWidth={2}
            dot={panel.points.length === 0 ? { r: 4, fill: color } : false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </figure>
  );
}
