"use client";

import { useState, useMemo } from "react";
import { ChevronUp, ChevronDown, AlertTriangle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { EventBreakdownEntry, SortConfig } from "./analytics-types";
import {
  formatEventType,
  getColorForEvent,
  computeDelta,
} from "./analytics-helpers";

interface AnalyticsFeatureTableProps {
  breakdown: EventBreakdownEntry[];
  totalEvents: number;
  compare: boolean;
}

type SortField = "event_type" | "count" | "share";

function sortRows(
  rows: ReadonlyArray<EventBreakdownEntry>,
  sort: SortConfig,
  total: number
): EventBreakdownEntry[] {
  const sorted = [...rows];
  sorted.sort((a, b) => {
    let cmp = 0;
    if (sort.field === "event_type") {
      cmp = a.event_type.localeCompare(b.event_type);
    } else if (sort.field === "count") {
      cmp = a.count - b.count;
    } else {
      const aPct = total > 0 ? a.count / total : 0;
      const bPct = total > 0 ? b.count / total : 0;
      cmp = aPct - bPct;
    }
    return sort.direction === "asc" ? cmp : -cmp;
  });
  return sorted;
}

function SortIcon({ field, sort }: { field: string; sort: SortConfig }) {
  if (sort.field !== field) {
    return <ChevronUp className="h-3 w-3 opacity-0 group-hover:opacity-30" />;
  }
  return sort.direction === "asc" ? (
    <ChevronUp className="h-3 w-3" />
  ) : (
    <ChevronDown className="h-3 w-3" />
  );
}

export function AnalyticsFeatureTable({
  breakdown,
  totalEvents,
  compare,
}: AnalyticsFeatureTableProps) {
  const [sort, setSort] = useState<SortConfig>({
    field: "count",
    direction: "desc",
  });

  const sorted = useMemo(
    () => sortRows(breakdown, sort, totalEvents),
    [breakdown, sort, totalEvents]
  );

  const unusedCount = breakdown.filter((e) => e.count === 0).length;

  function toggleSort(field: SortField) {
    setSort((prev) =>
      prev.field === field
        ? { field, direction: prev.direction === "asc" ? "desc" : "asc" }
        : { field, direction: "desc" }
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Feature Adoption
          {unusedCount > 0 && (
            <span className="inline-flex items-center gap-1 text-xs font-normal text-amber-500">
              <AlertTriangle className="h-3 w-3" />
              {unusedCount} unused
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left">
                {([
                  ["event_type", "Feature", ""],
                  ["count", "Count", "text-right"],
                  ["share", "Share %", "text-right"],
                ] as const).map(([field, label, align]) => (
                  <th key={field} className={`pb-2 font-medium text-muted-foreground cursor-pointer group ${align}`} onClick={() => toggleSort(field)}>
                    <span className={`inline-flex items-center gap-1 ${align ? "justify-end" : ""}`}>
                      {label} <SortIcon field={field} sort={sort} />
                    </span>
                  </th>
                ))}
                {compare && <th className="pb-2 font-medium text-muted-foreground text-right">Trend</th>}
                <th className="pb-2 font-medium text-muted-foreground text-right">Status</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((entry) => {
                const pct =
                  totalEvents > 0
                    ? ((entry.count / totalEvents) * 100).toFixed(1)
                    : "0.0";
                const color = getColorForEvent(entry.event_type);
                const isUnused = entry.count === 0;
                const delta = compare
                  ? computeDelta(entry.count, entry.prev_count)
                  : null;

                return (
                  <tr
                    key={entry.event_type}
                    className={`border-b last:border-0 ${
                      isUnused ? "bg-amber-50 dark:bg-amber-950/20" : ""
                    }`}
                  >
                    <td className="py-2">
                      <span
                        className="inline-block px-2 py-0.5 rounded text-xs font-medium"
                        style={{
                          backgroundColor: isUnused
                            ? "hsl(var(--muted))"
                            : color + "20",
                          color: isUnused
                            ? "hsl(var(--muted-foreground))"
                            : color,
                        }}
                      >
                        {formatEventType(entry.event_type)}
                      </span>
                    </td>
                    <td className="py-2 text-right font-mono">
                      {entry.count.toLocaleString()}
                    </td>
                    <td className="py-2 text-right text-muted-foreground">
                      {pct}%
                    </td>
                    {compare && (
                      <td className="py-2 text-right">
                        {delta ? (
                          <span
                            className={`text-xs ${
                              delta.direction === "up"
                                ? "text-green-600"
                                : delta.direction === "down"
                                  ? "text-red-500"
                                  : "text-muted-foreground"
                            }`}
                          >
                            {delta.direction === "up" && "+"}
                            {delta.direction === "down" && "-"}
                            {delta.pct}%
                          </span>
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            --
                          </span>
                        )}
                      </td>
                    )}
                    <td className="py-2 text-right">
                      {isUnused ? (
                        <span className="text-xs font-medium text-amber-600">
                          NOT USED
                        </span>
                      ) : (
                        <span className="text-xs font-medium text-green-600">
                          Active
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
