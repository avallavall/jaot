"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { useTranslations } from "next-intl";
import { useAuth } from "@/contexts/AuthContext";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { RefreshCw } from "lucide-react";
import type {
  FeatureAnalyticsOverview,
  AnalyticsFilters,
  Period,
  TimeSeriesMode,
  GroupedTimeSeriesEntry,
} from "@/components/admin/analytics/analytics-types";
import { PERIODS, buildQueryString } from "@/components/admin/analytics/analytics-helpers";
import {
  AnalyticsFilterBar,
  AnalyticsKPIGrid,
  AnalyticsTimeline,
  AnalyticsFeatureTable,
  AnalyticsFunnel,
  AnalyticsDomainHealth,
  AnalyticsGeography,
  AnalyticsRecentEvents,
} from "@/components/admin/analytics";

const INITIAL_FILTERS: AnalyticsFilters = {
  eventType: null,
  countryCode: null,
  domain: null,
  compare: false,
};

export default function FeatureAnalyticsPage() {
  const t = useTranslations("admin.featureAnalytics");
  const { user, isLoading: authLoading } = useAuth();

  const [data, setData] = useState<FeatureAnalyticsOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState<Period>("7d");
  const [filters, setFilters] = useState<AnalyticsFilters>(INITIAL_FILTERS);
  const [tsMode, setTsMode] = useState<TimeSeriesMode>("aggregate");
  const [groupedTs, setGroupedTs] = useState<GroupedTimeSeriesEntry[]>([]);

  const loadData = useCallback(
    async (p: Period, f: AnalyticsFilters, mode: TimeSeriesMode) => {
      setLoading(true);
      setError(null);
      try {
        const qs = buildQueryString(p, f);
        const groupParam = mode !== "aggregate" ? `&ts_group=${mode}` : "";
        const res = await fetch(
          `/api/v2/admin/marketplace/feature-analytics?${qs}${groupParam}`,
          { credentials: "include" }
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json: FeatureAnalyticsOverview = await res.json();
        setData(json);
        setGroupedTs(json.grouped_time_series ?? []);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unknown error");
      } finally {
        setLoading(false);
      }
    },
    []
  );

  // Re-fetch everything when period or filters change
  useEffect(() => {
    if (!authLoading && user) {
      loadData(period, filters, tsMode);
    }
  }, [period, filters, authLoading, user, loadData, tsMode]);

  const countryOptions = useMemo(
    () => (data?.country_distribution ?? []).map((c) => c.country_code),
    [data?.country_distribution]
  );

  const isEmpty = useMemo(
    () =>
      data != null &&
      data.kpi.total_events === 0 &&
      data.kpi.active_users === 0 &&
      data.kpi.events_today === 0,
    [data]
  );

  // Auth loading
  if (authLoading) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-28" />)}
        </div>
        <Skeleton className="h-80" />
      </div>
    );
  }

  if (!user) return null;

  if (error && !data) {
    return (
      <div className="space-y-6 p-6">
        <div>
          <h1 className="text-2xl font-semibold">{t("title")}</h1>
          <p className="text-muted-foreground">{t("description")}</p>
        </div>
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 gap-4">
            <p className="text-destructive">{error}</p>
            <button
              onClick={() => loadData(period, filters, tsMode)}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 text-sm font-medium"
            >
              <RefreshCw className="w-4 h-4" />
              Retry
            </button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">{t("title")}</h1>
          <p className="text-muted-foreground">{t("description")}</p>
        </div>
        <div className="flex gap-1 bg-muted rounded-lg p-1">
          {PERIODS.map((p) => (
            <button
              key={p.value}
              onClick={() => setPeriod(p.value)}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                period === p.value
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {t(p.labelKey)}
            </button>
          ))}
        </div>
      </div>

      <AnalyticsFilterBar
        filters={filters}
        onFiltersChange={setFilters}
        countryOptions={countryOptions}
      />

      {loading ? (
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
            {[1, 2, 3, 4, 5, 6].map((i) => <Skeleton key={i} className="h-28" />)}
          </div>
          <Skeleton className="h-80" />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Skeleton className="h-72" />
            <Skeleton className="h-72" />
          </div>
          <Skeleton className="h-64" />
        </div>
      ) : isEmpty ? (
        <Card>
          <CardContent className="flex items-center justify-center py-16">
            <p className="text-muted-foreground text-lg">{t("noEvents")}</p>
          </CardContent>
        </Card>
      ) : data ? (
        <>
          <AnalyticsKPIGrid
            kpi={data.kpi}
            breakdown={data.event_breakdown}
            compare={filters.compare}
          />

          <AnalyticsTimeline
            timeSeries={data.time_series.data}
            groupedTimeSeries={groupedTs}
            mode={tsMode}
            onModeChange={setTsMode}
          />

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <AnalyticsFeatureTable
              breakdown={data.event_breakdown}
              totalEvents={data.kpi.total_events}
              compare={filters.compare}
            />
            <AnalyticsFunnel steps={data.funnel.steps} />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <AnalyticsDomainHealth domains={data.domain_summary} />
            <AnalyticsGeography
              countries={data.country_distribution}
              onCountryClick={(code) =>
                setFilters({ ...filters, countryCode: code })
              }
            />
          </div>

          <AnalyticsRecentEvents period={period} filters={filters} />
        </>
      ) : null}
    </div>
  );
}
