"use client";

import { useState, useEffect, useCallback } from "react";
import { useTranslations } from "next-intl";
import { useAuth } from "@/contexts/AuthContext";
import { api } from "@/lib/api";
import type { AdminAnalytics } from "@/lib/types";
import { AnalyticsKPICards } from "@/components/author/AnalyticsKPICards";
import { AuthorLeaderboard, type AuthorLeaderboardEntry } from "@/components/admin/AuthorLeaderboard";
import { Skeleton } from "@/components/ui/skeleton";

type Period = "7d" | "30d" | "90d" | "all";

const PERIODS: { value: Period; labelKey: string }[] = [
  { value: "7d", labelKey: "period7d" },
  { value: "30d", labelKey: "period30d" },
  { value: "90d", labelKey: "period90d" },
  { value: "all", labelKey: "periodAll" },
];

export default function AdminAuthorAnalyticsPage() {
  const t = useTranslations("admin.marketplace");
  const tPeriod = useTranslations("author.analytics");
  const { user, isLoading: authLoading } = useAuth();

  const [period, setPeriod] = useState<Period>("30d");
  // `sellers` is the wire key of the legacy-path API response (renamed in the contract release).
  const [data, setData] = useState<(AdminAnalytics & { sellers: AuthorLeaderboardEntry[] }) | null>(null);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async (p: Period) => {
    setLoading(true);
    try {
      const result = await api.getAdminAuthorAnalytics(p);
      setData(result as AdminAnalytics & { sellers: AuthorLeaderboardEntry[] });
    } catch (err) {
      console.warn('Failed to load admin author analytics:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!authLoading && user) {
      loadData(period);
    }
  }, [period, authLoading, user, loadData]);

  if (authLoading) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      </div>
    );
  }

  if (!user) {
    return null;
  }

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{t("authorAnalytics")}</h1>
          <p className="text-muted-foreground">{t("platformTotals")}</p>
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
              {tPeriod(p.labelKey)}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="space-y-4">
          <div className="grid grid-cols-4 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
          <Skeleton className="h-80" />
        </div>
      ) : (
        <>
          {data && <AnalyticsKPICards data={data.platform_totals} />}

          {data && <AuthorLeaderboard authors={data.sellers} />}
        </>
      )}
    </div>
  );
}
