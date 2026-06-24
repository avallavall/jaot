"use client";

import { useState, useEffect, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type {
  AnalyticsFilters,
  PaginatedRecentEvents,
  RecentEvent,
} from "./analytics-types";
import {
  EVENT_TYPES,
  formatEventType,
  getColorForEvent,
  truncateId,
  relativeTime,
  buildQueryString,
} from "./analytics-helpers";

interface AnalyticsRecentEventsProps {
  period: string;
  filters: AnalyticsFilters;
}

const PAGE_SIZE = 20;

export function AnalyticsRecentEvents({
  period,
  filters,
}: AnalyticsRecentEventsProps) {
  const [page, setPage] = useState(1);
  const [eventTypeFilter, setEventTypeFilter] = useState("");
  const [data, setData] = useState<PaginatedRecentEvents | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchEvents = useCallback(
    async (p: number, etFilter: string) => {
      setLoading(true);
      try {
        const baseQs = buildQueryString(period, filters);
        const params = new URLSearchParams(baseQs);
        params.set("page", String(p));
        params.set("page_size", String(PAGE_SIZE));
        if (etFilter) params.set("event_type", etFilter);

        const res = await fetch(
          `/api/v2/admin/marketplace/feature-analytics/events?${params}`,
          { credentials: "include" }
        );
        if (!res.ok) {
          setData(null);
          return;
        }
        const json = await res.json();

        // Support both paginated and array response formats
        if (Array.isArray(json)) {
          setData({
            items: json as RecentEvent[],
            total: (json as RecentEvent[]).length,
            page: p,
            page_size: PAGE_SIZE,
          });
        } else {
          setData(json as PaginatedRecentEvents);
        }
      } catch {
        setData(null);
      } finally {
        setLoading(false);
      }
    },
    [period, filters]
  );

  // Fetch events; reset to page 1 when filters change (fetchEvents
  // identity changes when period/filters change via its deps).
  useEffect(() => {
    setPage(1);
    fetchEvents(1, eventTypeFilter);
  }, [fetchEvents, eventTypeFilter]);

  // Paginate within stable filters
  const handlePageChange = useCallback(
    (newPage: number) => {
      setPage(newPage);
      fetchEvents(newPage, eventTypeFilter);
    },
    [fetchEvents, eventTypeFilter]
  );

  const totalPages = data
    ? Math.max(1, Math.ceil(data.total / PAGE_SIZE))
    : 1;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Recent Events</CardTitle>
        <select
          value={eventTypeFilter}
          onChange={(e) => setEventTypeFilter(e.target.value)}
          className="h-8 rounded-md border border-input bg-background px-2 text-xs text-foreground"
        >
          <option value="">All types</option>
          {EVENT_TYPES.map((et) => (
            <option key={et} value={et}>
              {et}
            </option>
          ))}
        </select>
      </CardHeader>
      <CardContent>
        {loading ? (
          <p className="text-center text-muted-foreground py-8">Loading...</p>
        ) : !data || data.items.length === 0 ? (
          <p className="text-center text-muted-foreground py-8">
            No events recorded yet
          </p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left">
                    {["Event Type", "User ID", "Country", "Time", "Metadata"].map((h) => (
                      <th key={h} className="pb-2 font-medium text-muted-foreground">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((event) => (
                    <tr
                      key={event.id}
                      className="border-b last:border-0"
                    >
                      <td className="py-2">
                        <span
                          className="inline-block px-2 py-0.5 rounded text-xs font-medium"
                          style={{
                            backgroundColor:
                              getColorForEvent(event.event_type) + "20",
                            color: getColorForEvent(event.event_type),
                          }}
                        >
                          {formatEventType(event.event_type)}
                        </span>
                      </td>
                      <td className="py-2 font-mono text-xs text-muted-foreground">
                        {truncateId(event.user_id)}
                      </td>
                      <td className="py-2">
                        {event.country_code || "---"}
                      </td>
                      <td className="py-2 text-muted-foreground">
                        {relativeTime(event.created_at)}
                      </td>
                      <td className="py-2 font-mono text-xs text-muted-foreground max-w-[200px] truncate">
                        {event.metadata
                          ? JSON.stringify(event.metadata).slice(0, 60)
                          : "---"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex items-center justify-between pt-4">
              <button
                onClick={() => handlePageChange(Math.max(1, page - 1))}
                disabled={page <= 1}
                className="px-3 py-1.5 text-sm rounded-md border border-input bg-background disabled:opacity-40"
              >
                Previous
              </button>
              <span className="text-sm text-muted-foreground">
                Page {page} of {totalPages}
              </span>
              <button
                onClick={() => handlePageChange(Math.min(totalPages, page + 1))}
                disabled={page >= totalPages}
                className="px-3 py-1.5 text-sm rounded-md border border-input bg-background disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
