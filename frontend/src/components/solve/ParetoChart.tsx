"use client";

import { Fragment, useState, useMemo, useCallback } from "react";
import {
  Scatter,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Line,
  ComposedChart,
  Label,
} from "recharts";
import type { MultiObjectiveResult, ParetoPoint } from "@/lib/types";
import { ConceptTooltip } from "@/components/ui/concept-tooltip";
import { HelpTooltip } from "@/components/ui/help-tooltip";
import { TradeOffExplorer } from "@/components/solve/TradeOffExplorer";
import { useTranslations } from "next-intl";

interface ParetoChartProps {
  result: MultiObjectiveResult;
  /** Which pair of objectives to plot (indices into result.labels). Defaults to [0, 1]. */
  axisPair?: readonly [number, number];
}

export type IndexedPoint = ParetoPoint & { index: number };

interface ParetoTooltipProps {
  active?: boolean;
  payload?: Array<{ payload?: IndexedPoint }>;
  labels: readonly string[];
  axisPair: readonly [number, number];
}

// Color gradient from best (green-ish) to worst (orange)
const GRADIENT_COLORS = [
  "hsl(160, 65%, 45%)", // teal-green
  "hsl(140, 55%, 48%)",
  "hsl(100, 50%, 50%)",
  "hsl(60, 55%, 50%)",
  "hsl(35, 65%, 50%)",
  "hsl(15, 70%, 50%)",  // orange-red
];

function interpolateColor(ratio: number): string {
  const idx = ratio * (GRADIENT_COLORS.length - 1);
  const lower = Math.floor(idx);
  const upper = Math.min(lower + 1, GRADIENT_COLORS.length - 1);
  if (lower === upper) return GRADIENT_COLORS[lower];
  // Simple nearest color for performance
  return idx - lower < 0.5 ? GRADIENT_COLORS[lower] : GRADIENT_COLORS[upper];
}

function getObjectiveValue(point: ParetoPoint, index: number, labels: readonly string[]): number {
  // For indices 0 and 1, use the canonical f1/f2 fields
  if (index === 0) return point.f1;
  if (index === 1) return point.f2;
  // For 3+ objectives, read from objective_values by label, or fall back to f<N+1>
  const label = labels[index];
  if (label && point.objective_values?.[label] !== undefined) {
    return point.objective_values[label];
  }
  const fKey = `f${index + 1}`;
  const val = (point as unknown as Record<string, unknown>)[fKey];
  return typeof val === "number" ? val : 0;
}

function ParetoTooltip({ active, payload, labels, axisPair }: ParetoTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0]?.payload;
  if (!point) return null;

  const xIdx = axisPair[0];
  const yIdx = axisPair[1];

  return (
    <div className="bg-popover border border-border rounded-md shadow-md px-3 py-2 text-xs max-w-xs">
      <p className="font-semibold text-foreground mb-1.5">
        Point #{point.index + 1}
      </p>
      <div className="space-y-0.5 mb-2">
        <p className="text-muted-foreground">
          {labels[xIdx] ?? `Obj ${xIdx + 1}`}:{" "}
          <span className="text-foreground font-mono">
            {getObjectiveValue(point, xIdx, labels).toFixed(4)}
          </span>
        </p>
        <p className="text-muted-foreground">
          {labels[yIdx] ?? `Obj ${yIdx + 1}`}:{" "}
          <span className="text-foreground font-mono">
            {getObjectiveValue(point, yIdx, labels).toFixed(4)}
          </span>
        </p>
      </div>
      {Object.keys(point.solution).length > 0 && (
        <div className="border-t border-border pt-1.5 mt-1.5">
          <p className="text-muted-foreground/70 mb-1 font-medium">Variables:</p>
          <div className="space-y-0.5">
            {Object.entries(point.solution).slice(0, 8).map(([name, val]) => (
              <p key={name} className="text-muted-foreground">
                <span className="font-mono">{name}</span> ={" "}
                <span className="text-foreground font-mono">{val.toFixed(4)}</span>
              </p>
            ))}
            {Object.keys(point.solution).length > 8 && (
              <p className="text-muted-foreground/60 italic">
                +{Object.keys(point.solution).length - 8} more...
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function ParetoChart({ result, axisPair = [0, 1] }: ParetoChartProps) {
  const t = useTranslations("solve.charts.pareto");
  const tHelp = useTranslations("solve.helpTooltips");
  const [selectedIndices, setSelectedIndices] = useState<readonly number[]>([]);
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());

  const indexedPoints: IndexedPoint[] = useMemo(
    () => result.pareto_points.map((p, i) => ({ ...p, index: i })),
    [result.pareto_points]
  );

  // Project the selected axis pair onto _plotX / _plotY for Recharts
  type PlottablePoint = IndexedPoint & { _plotX: number; _plotY: number };

  const plottablePoints: PlottablePoint[] = useMemo(
    () =>
      indexedPoints.map((p) => ({
        ...p,
        _plotX: getObjectiveValue(p, axisPair[0], result.labels),
        _plotY: getObjectiveValue(p, axisPair[1], result.labels),
      })),
    [indexedPoints, axisPair, result.labels]
  );

  // Sort points by X axis value for the frontier line
  const sortedForLine = useMemo(
    () => [...plottablePoints].sort((a, b) => a._plotX - b._plotX),
    [plottablePoints]
  );

  // Find extreme points (lowest values on each axis)
  const extremes = useMemo(() => {
    if (plottablePoints.length === 0) return { bestX: null, bestY: null };
    const bestX = plottablePoints.reduce(
      (best, p) => (p._plotX < best._plotX ? p : best),
      plottablePoints[0],
    );
    const bestY = plottablePoints.reduce(
      (best, p) => (p._plotY < best._plotY ? p : best),
      plottablePoints[0],
    );
    return { bestX, bestY };
  }, [plottablePoints]);

  // Selected point objects for the trade-off explorer
  const selectedPointObjects: readonly IndexedPoint[] = useMemo(
    () => selectedIndices.map((idx) => indexedPoints[idx]).filter(Boolean),
    [selectedIndices, indexedPoints]
  );

  const togglePoint = useCallback((idx: number) => {
    setSelectedIndices((prev) => {
      if (prev.includes(idx)) {
        return prev.filter((i) => i !== idx);
      }
      // Keep max 2 selected
      if (prev.length >= 2) {
        return [prev[1], idx];
      }
      return [...prev, idx];
    });
  }, []);

  function toggleExpand(idx: number) {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) {
        next.delete(idx);
      } else {
        next.add(idx);
      }
      return next;
    });
  }

  // Memoized tooltip renderer
  const renderTooltip = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (props: any) => (
      <ParetoTooltip {...props} labels={result.labels} axisPair={axisPair} />
    ),
    [result.labels, axisPair],
  );

  // Memoized scatter point shape
  const renderShape = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (props: any) => {
      const { cx = 0, cy = 0, payload } = props as {
        cx: number;
        cy: number;
        payload?: IndexedPoint;
      };
      if (!payload) return <circle cx={Number(cx)} cy={Number(cy)} r={0} />;

      const isSelected = selectedIndices.includes(payload.index);
      const ratio = indexedPoints.length > 1
        ? payload.index / (indexedPoints.length - 1)
        : 0;
      const color = isSelected ? "var(--primary)" : interpolateColor(ratio);
      const isBestX = extremes.bestX?.index === payload.index;
      const isBestY = extremes.bestY?.index === payload.index;
      const isExtreme = isBestX || isBestY;

      return (
        <g>
          <circle
            cx={Number(cx)}
            cy={Number(cy)}
            r={isSelected ? 9 : isExtreme ? 7 : 6}
            fill={color}
            fillOpacity={isSelected ? 1 : 0.75}
            stroke={isSelected ? "var(--primary)" : isExtreme ? color : "transparent"}
            strokeWidth={isSelected ? 3 : isExtreme ? 2 : 0}
            strokeOpacity={isSelected ? 0.3 : 0.4}
            style={{ cursor: "pointer", transition: "r 0.15s, fill-opacity 0.15s" }}
            onClick={() => togglePoint(payload.index)}
          />
          {isBestX && !isBestY && (
            <text
              x={Number(cx)}
              y={Number(cy) - 14}
              textAnchor="middle"
              fontSize={10}
              fill="var(--muted-foreground)"
              fontWeight={500}
            >
              {t("bestLabel", { obj: result.labels[axisPair[0]] ?? t("objective1") })}
            </text>
          )}
          {isBestY && !isBestX && (
            <text
              x={Number(cx)}
              y={Number(cy) - 14}
              textAnchor="middle"
              fontSize={10}
              fill="var(--muted-foreground)"
              fontWeight={500}
            >
              {t("bestLabel", { obj: result.labels[axisPair[1]] ?? t("objective2") })}
            </text>
          )}
        </g>
      );
    },
    [selectedIndices, indexedPoints, extremes, togglePoint, t, result.labels, axisPair],
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-4 text-sm">
        <div className="flex items-center gap-2 px-3 py-1.5 bg-muted/40 rounded-md">
          <span className="text-muted-foreground">{t("paretoSolutions")}</span>
          <span className="font-semibold tabular-nums">{result.n_solved}</span>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 bg-muted/40 rounded-md">
          <span className="text-muted-foreground">{t("mode")}</span>
          <span className="font-semibold capitalize">{result.mode}</span>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 bg-muted/40 rounded-md">
          <span className="text-muted-foreground">{t("creditsUsed")}</span>
          <span className="font-semibold tabular-nums">{result.total_credits_used}</span>
        </div>
      </div>

      <div className="bg-card border border-border rounded-lg p-4" data-testid="pareto-chart">
        <h3 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-1.5">
          <ConceptTooltip termKey="pareto-front">{t("paretoFront")}</ConceptTooltip>
          <HelpTooltip content={tHelp("paretoFrontier")} side="right" size={14} />
        </h3>
        <ResponsiveContainer width="100%" height={420}>
          <ComposedChart
            data={sortedForLine}
            margin={{ top: 20, right: 40, bottom: 50, left: 50 }}
          >
            <CartesianGrid strokeDasharray="3 3" className="stroke-border/50" />
            <XAxis
              dataKey="_plotX"
              type="number"
              tick={{ fontSize: 11 }}
              tickLine={false}
              domain={["auto", "auto"]}
            >
              <Label
                value={result.labels[axisPair[0]] ?? t("objective1")}
                position="insideBottom"
                offset={-10}
                style={{ fontSize: 12, fontWeight: 500, fill: "var(--muted-foreground)" }}
              />
            </XAxis>
            <YAxis
              dataKey="_plotY"
              type="number"
              tick={{ fontSize: 11 }}
              tickLine={false}
              domain={["auto", "auto"]}
            >
              <Label
                value={result.labels[axisPair[1]] ?? t("objective2")}
                angle={-90}
                position="insideLeft"
                offset={-5}
                style={{ fontSize: 12, fontWeight: 500, fill: "var(--muted-foreground)" }}
              />
            </YAxis>
            <Tooltip content={renderTooltip} />

            <Line
              dataKey="_plotY"
              stroke="var(--primary)"
              strokeWidth={1.5}
              strokeOpacity={0.35}
              strokeDasharray="6 3"
              dot={false}
              activeDot={false}
              isAnimationActive={false}
            />

            {/* Scatter points with gradient colors and click support */}
            <Scatter
              dataKey="_plotY"
              data={plottablePoints}
              isAnimationActive={false}
              shape={renderShape}
            />
          </ComposedChart>
        </ResponsiveContainer>
        <p className="text-xs text-muted-foreground text-center mt-2">
          {t("clickToSelect")}
        </p>
      </div>

      <TradeOffExplorer
        selectedPoints={selectedPointObjects}
        labels={result.labels}
      />

      <div className="bg-card border border-border rounded-lg overflow-hidden">
        <div className="px-4 py-2 border-b border-border bg-muted/20">
          <span className="text-xs font-medium text-muted-foreground">
            {t("paretoOptimalSolutions", { count: result.n_solved })}
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-muted/40 border-b border-border">
                <th className="px-3 py-2 text-left font-medium text-muted-foreground w-10">#</th>
                <th className="px-3 py-2 text-right font-medium text-muted-foreground">
                  {result.labels[0] ?? t("objective1")}
                </th>
                <th className="px-3 py-2 text-right font-medium text-muted-foreground">
                  {result.labels[1] ?? t("objective2")}
                </th>
                <th className="px-3 py-2 text-right font-medium text-muted-foreground">{t("variablesHeader")}</th>
                <th className="px-3 py-2 text-center font-medium text-muted-foreground w-16">
                  {t("detail")}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {indexedPoints.map((point) => {
                const isSelected = selectedIndices.includes(point.index);
                const isExpanded = expandedRows.has(point.index);
                const varCount = Object.keys(point.solution).length;

                return (
                  <Fragment key={point.index}>
                    <tr
                      className={`transition-colors cursor-pointer ${
                        isSelected
                          ? "bg-primary/10 border-l-2 border-l-primary"
                          : "hover:bg-muted/20"
                      }`}
                      onClick={() => togglePoint(point.index)}
                      data-testid={`pareto-row-${point.index}`}
                    >
                      <td className="px-3 py-1.5 font-mono text-xs text-muted-foreground">
                        {point.index + 1}
                      </td>
                      <td className="px-3 py-1.5 text-right font-mono text-xs tabular-nums">
                        {point.f1.toFixed(4)}
                      </td>
                      <td className="px-3 py-1.5 text-right font-mono text-xs tabular-nums">
                        {point.f2.toFixed(4)}
                      </td>
                      <td className="px-3 py-1.5 text-right text-xs text-muted-foreground">
                        {t("varCount", { count: varCount })}
                      </td>
                      <td className="px-3 py-1.5 text-center">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleExpand(point.index);
                          }}
                          className="text-xs text-primary hover:underline"
                        >
                          {isExpanded ? t("hide") : t("show")}
                        </button>
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr className="bg-muted/10">
                        <td colSpan={5} className="px-4 py-3">
                          <div className="text-xs font-medium text-muted-foreground mb-2">
                            {t("solutionVariables")}
                          </div>
                          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
                            {Object.entries(point.solution).map(([name, val]) => (
                              <div
                                key={name}
                                className="flex justify-between gap-2 bg-background border border-border rounded px-2 py-1"
                              >
                                <span className="font-mono text-foreground truncate">{name}</span>
                                <span className="font-mono text-muted-foreground tabular-nums flex-shrink-0">
                                  {val.toFixed(4)}
                                </span>
                              </div>
                            ))}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
