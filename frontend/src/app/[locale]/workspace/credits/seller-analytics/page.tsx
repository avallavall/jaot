"use client";

import { useState, useEffect, useCallback } from "react";
import { useTranslations } from "next-intl";
import { useAuth } from "@/contexts/AuthContext";
import { api } from "@/lib/api";
import type {
  AnalyticsSummary,
  TimeSeriesDataPoint,
  GeoDistributionEntry,
  ModelPerformanceRow,
  ConversionFunnel,
} from "@/lib/types";
import { AnalyticsKPICards } from "@/components/seller/AnalyticsKPICards";
import { RevenueChart } from "@/components/seller/RevenueChart";
import { ConversionFunnel as ConversionFunnelChart } from "@/components/seller/ConversionFunnel";
import { GeoDistribution } from "@/components/seller/GeoDistribution";
import { TopModelsTable } from "@/components/seller/TopModelsTable";
import { OnboardingChecklist } from "@/components/seller/OnboardingChecklist";
import { VerificationRequest } from "@/components/seller/VerificationRequest";
import { Skeleton } from "@/components/ui/skeleton";

type Period = "7d" | "30d" | "90d" | "all";

const PERIODS: { value: Period; labelKey: string }[] = [
  { value: "7d", labelKey: "period7d" },
  { value: "30d", labelKey: "period30d" },
  { value: "90d", labelKey: "period90d" },
  { value: "all", labelKey: "periodAll" },
];

export default function SellerAnalyticsPage() {
  const t = useTranslations("seller.analytics");
  const { user, isLoading: authLoading } = useAuth();

  const [period, setPeriod] = useState<Period>("30d");
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [timeSeries, setTimeSeries] = useState<TimeSeriesDataPoint[]>([]);
  const [geo, setGeo] = useState<GeoDistributionEntry[]>([]);
  const [models, setModels] = useState<ModelPerformanceRow[]>([]);
  const [funnel, setFunnel] = useState<ConversionFunnel | null>(null);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async (p: Period) => {
    setLoading(true);
    try {
      const [summaryRes, tsRes, geoRes, modelsRes, funnelRes] =
        await Promise.all([
          api.getSellerAnalyticsSummary(p),
          api.getSellerAnalyticsTimeSeries(p),
          api.getSellerAnalyticsGeo(p),
          api.getSellerAnalyticsModels(p),
          api.getSellerAnalyticsFunnel(p),
        ]);
      setSummary(summaryRes);
      setTimeSeries(tsRes.data);
      setGeo(geoRes.data);
      setModels(modelsRes);
      setFunnel(funnelRes);
    } catch (err) {
      console.warn('Failed to load seller analytics:', err);
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
      {/* Onboarding checklist - auto-hides when all steps complete */}
      <OnboardingChecklist />

      <div className="flex items-center justify-between">
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

      <VerificationRequest />

      {loading ? (
        <div className="space-y-4">
          <div className="grid grid-cols-4 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
          <Skeleton className="h-80" />
          <Skeleton className="h-80" />
        </div>
      ) : (
        <>
          {summary && <AnalyticsKPICards data={summary} />}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <RevenueChart data={timeSeries} />
            {funnel && <ConversionFunnelChart data={funnel} />}
          </div>

          <GeoDistribution data={geo} />

          <TopModelsTable data={models} />
        </>
      )}
    </div>
  );
}
