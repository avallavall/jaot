"use client";

import { useMemo } from "react";
import {
  Activity,
  Users,
  TrendingUp,
  Zap,
  MessageSquare,
  ShoppingCart,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type {
  FeatureAnalyticsKPI,
  EventBreakdownEntry,
} from "./analytics-types";
import { computeDelta } from "./analytics-helpers";

interface AnalyticsKPIGridProps {
  kpi: FeatureAnalyticsKPI;
  breakdown: EventBreakdownEntry[];
  compare: boolean;
}

function useBreakdownMap(
  breakdown: ReadonlyArray<EventBreakdownEntry>
): Map<string, EventBreakdownEntry> {
  return useMemo(
    () => new Map(breakdown.map((e) => [e.event_type, e])),
    [breakdown]
  );
}

interface DeltaBadgeProps {
  current: number;
  previous: number | null | undefined;
  show: boolean;
}

function DeltaBadge({ current, previous, show }: DeltaBadgeProps) {
  if (!show) return null;
  const delta = computeDelta(current, previous);
  if (!delta) return null;

  if (delta.direction === "flat") {
    return (
      <span className="inline-flex items-center gap-0.5 text-xs text-muted-foreground">
        <Minus className="h-3 w-3" /> 0%
      </span>
    );
  }

  const isUp = delta.direction === "up";
  return (
    <span
      className={`inline-flex items-center gap-0.5 text-xs ${
        isUp ? "text-green-600" : "text-red-500"
      }`}
    >
      {isUp ? (
        <ArrowUpRight className="h-3 w-3" />
      ) : (
        <ArrowDownRight className="h-3 w-3" />
      )}
      {isUp ? "+" : "-"}
      {delta.pct}%
    </span>
  );
}

interface KPICardConfig {
  label: string;
  value: number;
  previous: number | null | undefined;
  icon: React.ReactNode;
}

export function AnalyticsKPIGrid({
  kpi,
  breakdown,
  compare,
}: AnalyticsKPIGridProps) {
  const bdMap = useBreakdownMap(breakdown);
  const solvesEntry = bdMap.get("solver.solve");
  const aiEntry = bdMap.get("ai_builder.message");
  const purchasesEntry = bdMap.get("marketplace.purchase");

  const cards: KPICardConfig[] = [
    {
      label: "Total Events",
      value: kpi.total_events,
      previous: kpi.prev_total_events,
      icon: <Activity className="h-4 w-4 text-muted-foreground" />,
    },
    {
      label: "Active Users",
      value: kpi.active_users,
      previous: kpi.prev_active_users,
      icon: <Users className="h-4 w-4 text-muted-foreground" />,
    },
    {
      label: "Solves",
      value: solvesEntry?.count ?? 0,
      previous: solvesEntry?.prev_count,
      icon: <Zap className="h-4 w-4 text-muted-foreground" />,
    },
    {
      label: "AI Messages",
      value: aiEntry?.count ?? 0,
      previous: aiEntry?.prev_count,
      icon: <MessageSquare className="h-4 w-4 text-muted-foreground" />,
    },
    {
      label: "Purchases",
      value: purchasesEntry?.count ?? 0,
      previous: purchasesEntry?.prev_count,
      icon: <ShoppingCart className="h-4 w-4 text-muted-foreground" />,
    },
    {
      label: "Events Today",
      value: kpi.events_today,
      previous: kpi.prev_events_today,
      icon: <TrendingUp className="h-4 w-4 text-muted-foreground" />,
    },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
      {cards.map((card) => (
        <Card key={card.label}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              {card.label}
            </CardTitle>
            {card.icon}
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {card.value.toLocaleString()}
            </div>
            <DeltaBadge
              current={card.value}
              previous={card.previous}
              show={compare}
            />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
