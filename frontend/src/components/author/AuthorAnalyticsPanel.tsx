"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { BarChart3 } from "lucide-react";

import { api } from "@/lib/api";
import type {
  AnalyticsSummary,
  AnalyticsTimeSeries,
  AnalyticsTimeSeriesPoint,
  ConversionFunnel,
  GeoDistribution,
  ModelPerformanceRow,
} from "@/lib/types";
import { AnalyticsKPICards } from "@/components/author/AnalyticsKPICards";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type Period = "7d" | "30d" | "90d" | "all";

const PERIODS: Period[] = ["7d", "30d", "90d", "all"];
const PERIOD_LABEL: Record<Period, string> = {
  "7d": "period7d",
  "30d": "period30d",
  "90d": "period90d",
  all: "periodAll",
};

/** Country names come from the browser, so we never ship a 250-row table x5 locales. */
function countryName(code: string, locale: string): string {
  try {
    return new Intl.DisplayNames([locale], { type: "region" }).of(code) ?? code;
  } catch {
    return code;
  }
}

const PERIOD_DAYS: Record<Period, number | null> = { "7d": 7, "30d": 30, "90d": 90, all: null };

/**
 * The API returns only the days that had events, so plotting it raw turns three
 * scattered days into three full-width blocks and reads as continuous activity.
 * Filling the quiet days with zeros is what makes the shape honest.
 */
export function fillMissingDays(
  points: AnalyticsTimeSeriesPoint[],
  period: Period,
  today: Date,
): AnalyticsTimeSeriesPoint[] {
  const span = PERIOD_DAYS[period];
  const iso = (d: Date) => d.toISOString().slice(0, 10);

  let start: Date;
  if (span !== null) {
    start = new Date(today);
    start.setUTCDate(start.getUTCDate() - (span - 1));
  } else {
    // "All time" has no fixed window: start at the first day we ever recorded.
    if (points.length === 0) return [];
    start = new Date(`${points[0].date}T00:00:00Z`);
  }

  const known = new Map(points.map((p) => [p.date, p]));
  const filled: AnalyticsTimeSeriesPoint[] = [];
  for (const cursor = new Date(start); iso(cursor) <= iso(today); cursor.setUTCDate(cursor.getUTCDate() + 1)) {
    const date = iso(cursor);
    filled.push(known.get(date) ?? { date, views: 0, impressions: 0, activations: 0 });
  }
  return filled;
}

/**
 * A short line of prose instead of a chart. The owner's complaint about the solve
 * analytics screen was that with little data a donut of a single colour and four
 * tiles repeating one number look ridiculous — so every panel here states what it
 * knows in words until there is genuinely something to plot.
 */
function NotEnoughYet({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 py-2 text-sm text-muted-foreground">
      <BarChart3 className="mt-0.5 h-4 w-4 shrink-0" />
      <p>{children}</p>
    </div>
  );
}

export function AuthorAnalyticsPanel({ locale }: { locale: string }) {
  const t = useTranslations("author.analytics");

  const [period, setPeriod] = useState<Period>("30d");
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [funnel, setFunnel] = useState<ConversionFunnel | null>(null);
  const [geo, setGeo] = useState<GeoDistribution | null>(null);
  const [models, setModels] = useState<ModelPerformanceRow[]>([]);
  const [series, setSeries] = useState<AnalyticsTimeSeries | null>(null);

  const load = useCallback(async (p: Period, isCurrent: () => boolean) => {
    setLoading(true);
    try {
      const [s, f, g, m, ts] = await Promise.all([
        api.getAuthorAnalyticsSummary(p),
        api.getAuthorAnalyticsFunnel(p),
        api.getAuthorAnalyticsGeo(p),
        api.getAuthorAnalyticsModels(p),
        api.getAuthorAnalyticsTimeSeries(p),
      ]);
      // Switching period fast must not let the older period's answer land last.
      if (!isCurrent()) return;
      setSummary(s);
      setFunnel(f);
      setGeo(g);
      setModels(m);
      setSeries(ts);
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    load(period, () => !cancelled);
    return () => {
      cancelled = true;
    };
  }, [load, period]);

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  const activeDays = series?.data.filter(
    (d) => d.views > 0 || d.impressions > 0 || d.activations > 0,
  ).length ?? 0;
  const days = fillMissingDays(series?.data ?? [], period, new Date());
  const peakViews = Math.max(...days.map((d) => d.views), 1);
  const countries = geo?.data ?? [];
  const totalGeo = countries.reduce((acc, c) => acc + c.count, 0);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-2">
        {PERIODS.map((p) => (
          <Button
            key={p}
            size="sm"
            variant={p === period ? "default" : "outline"}
            onClick={() => setPeriod(p)}
          >
            {t(PERIOD_LABEL[p])}
          </Button>
        ))}
      </div>

      {summary && <AnalyticsKPICards data={summary} />}

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-medium">{t("funnelTitle")}</CardTitle>
        </CardHeader>
        <CardContent>
          {!funnel || funnel.impressions === 0 ? (
            <NotEnoughYet>{t("funnelEmpty")}</NotEnoughYet>
          ) : (
            <div className="space-y-3">
              {(
                [
                  ["funnelImpressions", funnel.impressions],
                  ["funnelViews", funnel.views],
                  ["funnelAdoptions", funnel.activations],
                ] as const
              ).map(([key, value]) => (
                <div key={key}>
                  <div className="mb-1 flex justify-between text-sm">
                    <span>{t(key)}</span>
                    <span className="tabular-nums font-medium">{value.toLocaleString()}</span>
                  </div>
                  <div className="h-2 w-full rounded-full bg-muted">
                    <div
                      className="h-2 rounded-full bg-primary"
                      style={{ width: `${(value / funnel.impressions) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-medium">{t("trendTitle")}</CardTitle>
        </CardHeader>
        <CardContent>
          {activeDays < 2 ? (
            <NotEnoughYet>{t("trendEmpty", { days: activeDays })}</NotEnoughYet>
          ) : (
            <div className="flex h-24 items-end gap-px">
              {days.map((d) => (
                <div
                  key={d.date}
                  className="min-w-px flex-1 rounded-t bg-primary/70"
                  style={{ height: `${Math.max((d.views / peakViews) * 100, 2)}%` }}
                  title={`${d.date}: ${d.views}`}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-medium">{t("geoTitle")}</CardTitle>
        </CardHeader>
        <CardContent>
          {countries.length === 0 ? (
            /* "No countries" and "no visits" are different facts: the geo query
               drops views whose country is unknown, so with visits recorded and
               no country we must say that, not claim nobody came. */
            <NotEnoughYet>
              {(summary?.total_views ?? 0) > 0
                ? t("geoUnknown", { views: summary!.total_views })
                : t("geoEmpty")}
            </NotEnoughYet>
          ) : countries.length === 1 ? (
            /* One country is not a distribution — say it in words, don't draw it. */
            <NotEnoughYet>
              {t("geoSingle", {
                count: countries[0].count,
                country: countryName(countries[0].country, locale),
              })}
            </NotEnoughYet>
          ) : (
            <div className="space-y-2">
              {countries.map((c) => (
                <div key={c.country} className="flex items-center gap-3">
                  <span className="w-32 shrink-0 truncate text-sm">
                    {countryName(c.country, locale)}
                  </span>
                  <div className="h-2 flex-1 rounded-full bg-muted">
                    <div
                      className="h-2 rounded-full bg-primary"
                      style={{ width: `${(c.count / totalGeo) * 100}%` }}
                    />
                  </div>
                  <span className="w-12 shrink-0 text-right text-sm tabular-nums">{c.count}</span>
                </div>
              ))}
              {/* Don't let the bars imply they cover every visit. */}
              {(summary?.total_views ?? 0) > totalGeo && (
                <p className="pt-1 text-xs text-muted-foreground">
                  {t("geoCoverage", { known: totalGeo, total: summary!.total_views })}
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-medium">{t("perModelTitle")}</CardTitle>
        </CardHeader>
        <CardContent>
          {models.length === 0 ? (
            <NotEnoughYet>{t("perModelEmpty")}</NotEnoughYet>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("colModel")}</TableHead>
                  <TableHead className="text-right">{t("colViews")}</TableHead>
                  <TableHead className="text-right">{t("colAdoptions")}</TableHead>
                  <TableHead className="text-right">{t("conversionRate")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {models.map((m) => (
                  <TableRow key={m.model_id}>
                    <TableCell className="font-medium">{m.model_name}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {m.views.toLocaleString()}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {m.activations.toLocaleString()}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {m.conversion_rate}%
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
