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

import type { ComparisonMatrixRow } from "@/lib/types";

import { performanceProfile, profileSeries } from "./performance-profile";

/** Five tokens, five solvers. The order follows the columns of the matrix. */
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

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function factor(value: number): string {
  return `${value.toLocaleString(undefined, { maximumFractionDigits: value < 10 ? 1 : 0 })}x`;
}

/**
 * The performance profile of a solver matrix.
 *
 * Renders nothing at all when the batch cannot support one — too few datasets,
 * or fewer than two solvers that proved anything. A chart drawn on four runs
 * moves a quarter of its height when one dataset changes hands, and a reader
 * cannot tell that from a real difference between solvers.
 */
export function PerformanceProfileChart({
  rows,
  solverNames,
}: {
  rows: ComparisonMatrixRow[];
  solverNames: string[];
}) {
  const t = useTranslations("studio");

  const profile = useMemo(
    () => performanceProfile(rows, solverNames),
    [rows, solverNames],
  );
  const series = useMemo(() => (profile ? profileSeries(profile) : []), [profile]);

  if (!profile) return null;

  const colorOf = (solver: string) =>
    CHART_COLORS[solverNames.indexOf(solver) % CHART_COLORS.length];

  const best = [...profile.curves].sort((a, b) => b.wins - a.wins)[0];

  return (
    <div className="space-y-2" data-testid="matrix-performance-profile">
      <div>
        <h4 className="text-sm font-medium">{t("matrix.profile.title")}</h4>
        <p className="text-xs text-muted-foreground">
          {t("matrix.profile.subtitle", { instances: profile.instances })}
        </p>
      </div>

      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={series} margin={{ top: 8, right: 16, bottom: 24, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis
            dataKey="tau"
            type="number"
            scale="log"
            domain={[1, profile.maxRatio]}
            allowDataOverflow
            tick={AXIS_TICK}
            tickFormatter={factor}
            label={{
              value: t("matrix.profile.xAxis"),
              position: "insideBottom",
              offset: -12,
              style: AXIS_TICK,
            }}
          />
          <YAxis
            type="number"
            domain={[0, 1]}
            tick={AXIS_TICK}
            tickFormatter={percent}
            width={44}
          />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            labelFormatter={(value) =>
              t("matrix.profile.within", { factor: factor(Number(value)) })
            }
            formatter={(value, name) => [percent(Number(value)), String(name)]}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {profile.curves.map((curve) => (
            <Line
              key={curve.solver}
              type="stepAfter"
              dataKey={curve.solver}
              name={curve.solver}
              stroke={colorOf(curve.solver)}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>

      <div className="space-y-1 text-xs text-muted-foreground">
        <p>{t("matrix.profile.howToRead")}</p>
        {best && best.wins > 0 ? (
          <p>
            {t("matrix.profile.fastestMost", {
              solver: best.solver,
              wins: best.wins,
              instances: profile.instances,
            })}
          </p>
        ) : null}
        {profile.neverSolved.length > 0 ? (
          <p>
            {t("matrix.profile.neverSolved", { solvers: profile.neverSolved.join(", ") })}
          </p>
        ) : null}
      </div>
    </div>
  );
}
