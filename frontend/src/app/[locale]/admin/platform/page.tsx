"use client";

import { useState, useEffect, useCallback } from "react";
import { useTranslations } from "next-intl";
import { RefreshCw } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { PERIODS } from "@/components/admin/platform/platform-helpers";
import { HealthSection } from "@/components/admin/platform/HealthSection";
import { AiSection } from "@/components/admin/platform/AiSection";
import { ReliabilitySection } from "@/components/admin/platform/ReliabilitySection";
import type {
  PlatformOverview,
  Reliability,
  AiUsage,
} from "@/components/admin/platform/platform-types";

export default function PlatformAnalyticsPage() {
  const t = useTranslations("admin.platformAnalytics");
  const { user, isLoading: authLoading } = useAuth();

  const [days, setDays] = useState(30);
  const [overview, setOverview] = useState<PlatformOverview | null>(null);
  const [reliability, setReliability] = useState<Reliability | null>(null);
  const [ai, setAi] = useState<AiUsage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async (d: number) => {
    setLoading(true);
    setError(null);
    try {
      const [o, r, a] = await Promise.all([
        fetch(`/api/v2/admin/platform/overview?days=${d}`, { credentials: "include" }),
        fetch(`/api/v2/admin/platform/reliability?days=${d}`, { credentials: "include" }),
        fetch(`/api/v2/admin/platform/ai?days=${d}`, { credentials: "include" }),
      ]);
      if (!o.ok || !r.ok || !a.ok) {
        throw new Error(`HTTP ${o.status} / ${r.status} / ${a.status}`);
      }
      setOverview(await o.json());
      setReliability(await r.json());
      setAi(await a.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!authLoading && user) loadData(days);
  }, [days, authLoading, user, loadData]);

  if (authLoading) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {[1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-72" />
      </div>
    );
  }

  if (!user) return null;

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-2xl font-semibold">{t("title")}</h1>
          <p className="text-muted-foreground">{t("description")}</p>
        </div>
        <div className="flex gap-1 rounded-lg bg-muted p-1">
          {PERIODS.map((p) => (
            <button
              key={p.days}
              onClick={() => setDays(p.days)}
              className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                days === p.days
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {t(p.labelKey)}
            </button>
          ))}
        </div>
      </div>

      {error && !overview ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center gap-4 py-12">
            <p className="text-destructive">{t("loadError")}</p>
            <button
              onClick={() => loadData(days)}
              className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              <RefreshCw className="h-4 w-4" />
              {t("retry")}
            </button>
          </CardContent>
        </Card>
      ) : loading ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
        </div>
      ) : overview && reliability && ai ? (
        <div className="space-y-10">
          <HealthSection data={overview} />
          <AiSection data={ai} />
          <ReliabilitySection data={reliability} />
        </div>
      ) : null}
    </div>
  );
}
