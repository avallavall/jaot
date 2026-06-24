"use client";

import { useMemo, useRef } from "react";
import type React from "react";
import { useTranslations } from "next-intl";
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

interface TrendPoint {
  date: string;
  dateMs: number;
  objective: number;
  credits: number;
  executionId: string;
  origin: "manual" | "triggered";
}

interface Props {
  executions: ModelExecution[];
  chartRef?: React.RefObject<HTMLDivElement>;
}

const TICK_STYLE = { fontSize: 11, fill: "var(--muted-foreground)" };
const GRID_STYLE = { strokeDasharray: "3 3", stroke: "var(--border)" };
const TOOLTIP_STYLE = {
  contentStyle: {
    background: "var(--card)",
    border: "1px solid var(--border)",
    fontSize: 12,
    borderRadius: "6px",
    padding: "8px 12px",
  },
};

function renderShape(props: { cx?: number; cy?: number; payload?: { origin?: string } }) {
  const { cx = 0, cy = 0, payload } = props;
  const color = "hsl(var(--primary))";
  if (payload?.origin === "triggered") {
    // Diamond shape
    const s = 7;
    return (
      <polygon
        points={`${cx},${cy - s} ${cx + s},${cy} ${cx},${cy + s} ${cx - s},${cy}`}
        fill={color}
      />
    );
  }
  // Circle for manual (default)
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
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div
      style={{
        background: "var(--card)",
        border: "1px solid var(--border)",
        fontSize: 12,
        borderRadius: "6px",
        padding: "8px 12px",
      }}
    >
      <p className="font-medium text-foreground mb-1">
        {new Date(d.dateMs).toLocaleString()}
      </p>
      <p className="text-muted-foreground">
        Objective: {d.objective.toFixed(4)}
      </p>
      <p className="text-muted-foreground">Credits used: {d.credits}</p>
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
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div
      style={{
        background: "var(--card)",
        border: "1px solid var(--border)",
        fontSize: 12,
        borderRadius: "6px",
        padding: "8px 12px",
      }}
    >
      <p className="font-medium text-foreground mb-1">
        {new Date(d.dateMs).toLocaleString()}
      </p>
      <p className="text-muted-foreground">
        Objective: {d.objective.toFixed(4)}
      </p>
      <p className="text-muted-foreground">Credits used: {d.credits}</p>
      <p className="text-muted-foreground capitalize">Origin: {d.origin}</p>
    </div>
  );
}

export default function ObjectiveTrendChart({ executions, chartRef }: Props) {
  const t = useTranslations("solve.charts.objectiveTrend");
  const internalRef = useRef<HTMLDivElement>(null);
  const containerRef = chartRef ?? internalRef;

  // Build trend points from completed executions with objective values
  const trendData = useMemo<TrendPoint[]>(() => {
    return executions
      .filter(
        (e) => e.status === "completed" && e.objective_value != null
      )
      .map((e) => ({
        date: new Date(e.created_at).toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        }),
        dateMs: new Date(e.created_at).getTime(),
        objective: e.objective_value as number,
        credits: e.credits_consumed,
        executionId: e.id,
        origin: (e.origin ?? "manual") as "manual" | "triggered",
      }))
      .sort((a, b) => a.dateMs - b.dateMs);
  }, [executions]);

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
              <Tooltip content={<CustomTooltip />} {...TOOLTIP_STYLE} />
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
                  new Date(v).toLocaleDateString("en-US", {
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
          <p className="text-xs text-muted-foreground mt-2 text-center">
            ● {t("legendManual")} &nbsp; ◆ {t("legendTriggered")}
          </p>
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
              <Tooltip content={<CustomTooltip />} {...TOOLTIP_STYLE} />
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
