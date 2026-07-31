"use client";

import { useMemo, useRef } from "react";
import type React from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  LineChart,
  Line,
  ScatterChart,
  Scatter,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  ZAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import type { ModelExecution } from "@/lib/types";
import { apiDate } from "@/lib/dates";
import {
  ORIGIN_CHART_COLORS,
  UNKNOWN_ORIGIN_COLOR,
  isOriginKey,
} from "@/lib/execution-origin";

interface TrendPoint {
  date: string;
  dateMs: number;
  objective: number;
  executionId: string;
  /** The persisted slug, not a two-value guess: nine origins reach this chart. */
  origin: string;
}

interface Props {
  executions: ModelExecution[];
  chartRef?: React.RefObject<HTMLDivElement>;
}

const TICK_STYLE = { fontSize: 11, fill: "var(--muted-foreground)" };
const GRID_STYLE = { strokeDasharray: "3 3", stroke: "var(--border)" };

/** Applied by the custom tooltip bodies below. recharts' own `contentStyle` prop
 * is not an option here: it is read by `DefaultTooltipContent`, which a `content`
 * of our own replaces — it used to be passed anyway, doing nothing. */
const TOOLTIP_BOX_STYLE = {
  background: "var(--card)",
  border: "1px solid var(--border)",
  fontSize: 12,
  borderRadius: "6px",
  padding: "8px 12px",
} as const;

/**
 * A point is coloured by its origin and keeps the diamond for a triggered run.
 *
 * Every point used to be one colour with two shapes, and the legend called the
 * circle "Manual" — which mislabels the eight other origins that draw a circle.
 * Naming the shape instead ("every other origin") was honest but told a reader
 * with nothing but manual runs less than the wrong label did. The palette every
 * other surface now uses gives the chart the same nine-way encoding, and the
 * legend below lists only the origins actually present.
 */
function renderShape(props: { cx?: number; cy?: number; payload?: { origin?: string } }) {
  const { cx = 0, cy = 0, payload } = props;
  const origin = payload?.origin;
  const color = isOriginKey(origin) ? ORIGIN_CHART_COLORS[origin] : UNKNOWN_ORIGIN_COLOR;
  if (origin === "triggered") {
    // Diamond shape
    const s = 7;
    return (
      <polygon
        points={`${cx},${cy - s} ${cx + s},${cy} ${cx},${cy + s} ${cx - s},${cy}`}
        fill={color}
      />
    );
  }
  return <circle cx={cx} cy={cy} r={5} fill={color} />;
}

interface TooltipPayloadEntry {
  payload: TrendPoint;
}

function CustomTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: TooltipPayloadEntry[];
}) {
  const t = useTranslations("solve.charts.objectiveTrend");
  const locale = useLocale();
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div style={TOOLTIP_BOX_STYLE}>
      <p className="font-medium text-foreground mb-1">
        {new Date(d.dateMs).toLocaleString(locale)}
      </p>
      <p className="text-muted-foreground">
        {t("objective", { value: d.objective.toFixed(4) })}
      </p>
    </div>
  );
}

// Custom tooltip for scatter — payload[0].payload is the data point
function ScatterCustomTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: TrendPoint }[];
}) {
  const t = useTranslations("solve.charts.objectiveTrend");
  const tOrigin = useTranslations("solve.origin");
  const locale = useLocale();
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  // A slug this build does not know is shown as-is rather than mislabelled.
  const originLabel = isOriginKey(d.origin) ? tOrigin(d.origin) : d.origin;
  return (
    <div style={TOOLTIP_BOX_STYLE}>
      <p className="font-medium text-foreground mb-1">
        {new Date(d.dateMs).toLocaleString(locale)}
      </p>
      <p className="text-muted-foreground">
        {t("objective", { value: d.objective.toFixed(4) })}
      </p>
      <p className="text-muted-foreground">{t("origin", { origin: originLabel })}</p>
    </div>
  );
}

export default function ObjectiveTrendChart({ executions, chartRef }: Props) {
  const t = useTranslations("solve.charts.objectiveTrend");
  const tOrigin = useTranslations("solve.origin");
  // Dates followed the browser's locale or a hardcoded "en-US" while the labels
  // around them were translated, so the axis and the tooltip disagreed.
  const locale = useLocale();
  const internalRef = useRef<HTMLDivElement>(null);
  const containerRef = chartRef ?? internalRef;

  // Build trend points from completed executions with objective values
  const trendData = useMemo<TrendPoint[]>(() => {
    return executions
      .filter(
        (e) => e.status === "completed" && e.objective_value != null
      )
      .map((e) => ({
        date: apiDate(e.created_at).toLocaleDateString(locale, {
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        }),
        dateMs: apiDate(e.created_at).getTime(),
        objective: e.objective_value as number,
        executionId: e.id,
        origin: e.origin ?? "manual",
      }))
      .sort((a, b) => a.dateMs - b.dateMs);
  }, [executions, locale]);

  // Only the origins in view, largest group first — a legend should not name a
  // category the chart does not contain.
  const presentOrigins = useMemo(() => {
    const counts = new Map<string, number>();
    for (const point of trendData) {
      counts.set(point.origin, (counts.get(point.origin) ?? 0) + 1);
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([origin]) => ({
        origin,
        label: isOriginKey(origin) ? tOrigin(origin) : origin,
        color: isOriginKey(origin) ? ORIGIN_CHART_COLORS[origin] : UNKNOWN_ORIGIN_COLOR,
      }));
  }, [trendData, tOrigin]);

  if (trendData.length === 0) {
    return (
      <div className="flex items-center justify-center h-[280px]">
        <p className="text-sm text-muted-foreground">
          {t("noData")}
        </p>
      </div>
    );
  }

  return (
    <div ref={containerRef as React.RefObject<HTMLDivElement>}>
      <Tabs defaultValue="line">
        <TabsList>
          <TabsTrigger value="line">{t("line")}</TabsTrigger>
          <TabsTrigger value="scatter">{t("scatter")}</TabsTrigger>
          <TabsTrigger value="bar">{t("bar")}</TabsTrigger>
        </TabsList>

        {/* ---- Line Chart ---- */}
        <TabsContent value="line">
          <ResponsiveContainer width="100%" height={280}>
            <LineChart
              data={trendData}
              margin={{ top: 10, right: 20, left: 0, bottom: 5 }}
            >
              <CartesianGrid {...GRID_STYLE} />
              <XAxis
                dataKey="date"
                tick={TICK_STYLE}
                interval="preserveStartEnd"
              />
              <YAxis tick={TICK_STYLE} width={70} />
              <Tooltip content={<CustomTooltip />} />
              <Line
                type="monotone"
                dataKey="objective"
                stroke="var(--primary)"
                strokeWidth={2}
                dot={{ r: 4 }}
                activeDot={{ r: 6 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </TabsContent>

        {/* ---- Scatter Chart (with origin-aware marker shapes) ---- */}
        <TabsContent value="scatter">
          <ResponsiveContainer width="100%" height={280}>
            <ScatterChart
              margin={{ top: 10, right: 20, left: 0, bottom: 5 }}
            >
              <CartesianGrid {...GRID_STYLE} />
              <XAxis
                dataKey="dateMs"
                type="number"
                domain={["auto", "auto"]}
                tickFormatter={(v: number) =>
                  new Date(v).toLocaleDateString(locale, {
                    month: "short",
                    day: "numeric",
                  })
                }
                tick={TICK_STYLE}
              />
              <YAxis
                dataKey="objective"
                tick={TICK_STYLE}
                width={70}
              />
              <ZAxis range={[40, 40]} />
              <Tooltip content={<ScatterCustomTooltip />} />
              <Scatter data={trendData} fill="var(--primary)" // eslint-disable-next-line @typescript-eslint/no-explicit-any
              shape={renderShape as any} />
            </ScatterChart>
          </ResponsiveContainer>
          <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 mt-2 text-xs text-muted-foreground">
            {presentOrigins.map(({ origin, label, color }) => (
              <span key={origin} className="inline-flex items-center gap-1">
                <span aria-hidden style={{ color }}>
                  {origin === "triggered" ? "◆" : "●"}
                </span>
                {label}
              </span>
            ))}
          </div>
        </TabsContent>

        {/* ---- Bar Chart ---- */}
        <TabsContent value="bar">
          <ResponsiveContainer width="100%" height={280}>
            <BarChart
              data={trendData}
              margin={{ top: 10, right: 20, left: 0, bottom: 5 }}
            >
              <CartesianGrid {...GRID_STYLE} />
              <XAxis
                dataKey="date"
                tick={TICK_STYLE}
                interval="preserveStartEnd"
              />
              <YAxis tick={TICK_STYLE} width={70} />
              <Tooltip content={<CustomTooltip />} />
              <Bar
                dataKey="objective"
                fill="var(--primary)"
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </TabsContent>
      </Tabs>
    </div>
  );
}
