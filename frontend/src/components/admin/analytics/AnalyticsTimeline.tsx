"use client";

import { useMemo } from "react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type {
  TimeSeriesEntry,
  GroupedTimeSeriesEntry,
  TimeSeriesMode,
} from "./analytics-types";
import { DOMAIN_COLORS, TOOLTIP_STYLE, formatDate } from "./analytics-helpers";

interface AnalyticsTimelineProps {
  timeSeries: TimeSeriesEntry[];
  groupedTimeSeries: GroupedTimeSeriesEntry[];
  mode: TimeSeriesMode;
  onModeChange: (mode: TimeSeriesMode) => void;
}

const MODE_LABELS: { value: TimeSeriesMode; label: string }[] = [
  { value: "aggregate", label: "Aggregate" },
  { value: "domain", label: "By Domain" },
  { value: "event_type", label: "By Event Type" },
];

const STACKED_COLORS = [
  "#3b82f6", "#22c55e", "#a855f7", "#f97316", "#eab308",
  "#06b6d4", "#ec4899", "#8b5cf6", "#ef4444", "#14b8a6",
];

function buildGroupedData(
  entries: ReadonlyArray<GroupedTimeSeriesEntry>
): { data: Record<string, string | number>[]; keys: string[] } {
  const keySet = new Set<string>();
  const data = entries.map((entry) => {
    const row: Record<string, string | number> = {
      label: formatDate(entry.date),
    };
    for (const [key, val] of Object.entries(entry.series)) {
      row[key] = val;
      keySet.add(key);
    }
    return row;
  });
  return { data, keys: Array.from(keySet) };
}

function colorForKey(key: string, index: number): string {
  return DOMAIN_COLORS[key] ?? STACKED_COLORS[index % STACKED_COLORS.length];
}

export function AnalyticsTimeline({
  timeSeries,
  groupedTimeSeries,
  mode,
  onModeChange,
}: AnalyticsTimelineProps) {
  const aggregateData = useMemo(
    () => timeSeries.map((d) => ({ ...d, label: formatDate(d.date) })),
    [timeSeries]
  );

  const grouped = useMemo(
    () => buildGroupedData(groupedTimeSeries),
    [groupedTimeSeries]
  );
  const showGrouped = mode !== "aggregate" && grouped.data.length > 0;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Event Trends</CardTitle>
        <div className="flex gap-1 bg-muted rounded-lg p-1">
          {MODE_LABELS.map((m) => (
            <button
              key={m.value}
              onClick={() => onModeChange(m.value)}
              className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                mode === m.value
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
      </CardHeader>
      <CardContent>
        {(showGrouped ? grouped.data.length : aggregateData.length) > 0 ? (
          <ResponsiveContainer width="100%" height={320}>
            {showGrouped ? (
              <AreaChart data={grouped.data}>
                <defs>
                  {grouped.keys.map((key, i) => (
                    <linearGradient
                      key={key}
                      id={`grad-${key}`}
                      x1="0"
                      y1="0"
                      x2="0"
                      y2="1"
                    >
                      <stop
                        offset="5%"
                        stopColor={colorForKey(key, i)}
                        stopOpacity={0.3}
                      />
                      <stop
                        offset="95%"
                        stopColor={colorForKey(key, i)}
                        stopOpacity={0}
                      />
                    </linearGradient>
                  ))}
                </defs>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis dataKey="label" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                {grouped.keys.map((key, i) => (
                  <Area
                    key={key}
                    type="monotone"
                    dataKey={key}
                    stackId="1"
                    stroke={colorForKey(key, i)}
                    fill={`url(#grad-${key})`}
                    strokeWidth={2}
                  />
                ))}
              </AreaChart>
            ) : (
              <AreaChart data={aggregateData}>
                <defs>
                  <linearGradient
                    id="colorCount"
                    x1="0"
                    y1="0"
                    x2="0"
                    y2="1"
                  >
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 12 }}
                  className="text-muted-foreground"
                />
                <YAxis tick={{ fontSize: 12 }} className="text-muted-foreground" />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Area
                  type="monotone"
                  dataKey="count"
                  stroke="#3b82f6"
                  fillOpacity={1}
                  fill="url(#colorCount)"
                  strokeWidth={2}
                />
              </AreaChart>
            )}
          </ResponsiveContainer>
        ) : (
          <p className="text-center text-muted-foreground py-12">
            No events recorded yet
          </p>
        )}
      </CardContent>
    </Card>
  );
}
