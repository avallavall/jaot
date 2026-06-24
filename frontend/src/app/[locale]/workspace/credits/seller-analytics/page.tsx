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
  FeaturedPlacement,
  ModelCatalogItem,
} from "@/lib/types";
import { AnalyticsKPICards } from "@/components/seller/AnalyticsKPICards";
import { RevenueChart } from "@/components/seller/RevenueChart";
import { ConversionFunnel as ConversionFunnelChart } from "@/components/seller/ConversionFunnel";
import { GeoDistribution } from "@/components/seller/GeoDistribution";
import { TopModelsTable } from "@/components/seller/TopModelsTable";
import { OnboardingChecklist } from "@/components/seller/OnboardingChecklist";
import { PromotionPurchase } from "@/components/seller/PromotionPurchase";
import { VerificationRequest } from "@/components/seller/VerificationRequest";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

type Period = "7d" | "30d" | "90d" | "all";

const PERIODS: { value: Period; labelKey: string }[] = [
  { value: "7d", labelKey: "period7d" },
  { value: "30d", labelKey: "period30d" },
  { value: "90d", labelKey: "period90d" },
  { value: "all", labelKey: "periodAll" },
];

export default function SellerAnalyticsPage() {
  const t = useTranslations("seller.analytics");
  const tp = useTranslations("seller.promotions");
  const { user, isLoading: authLoading } = useAuth();

  const [period, setPeriod] = useState<Period>("30d");
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [timeSeries, setTimeSeries] = useState<TimeSeriesDataPoint[]>([]);
  const [geo, setGeo] = useState<GeoDistributionEntry[]>([]);
  const [models, setModels] = useState<ModelPerformanceRow[]>([]);
  const [funnel, setFunnel] = useState<ConversionFunnel | null>(null);
  const [activePlacements, setActivePlacements] = useState<FeaturedPlacement[]>([]);
  const [sellerModels, setSellerModels] = useState<ModelCatalogItem[]>([]);
  const [loading, setLoading] = useState(true);

  const loadPlacements = useCallback(async () => {
    try {
      const [placementsRes] = await Promise.all([
        api.getActivePlacements(),
        api.getMyModels({ page_size: 100 }),
      ]);
      setActivePlacements(placementsRes.items);
      // Convert org models to catalog items for the promotion dialog
      // We use catalog endpoint to get proper catalog items for published models
      try {
        const me = await api.getMe();
        const orgModels = await api.getOrgModels(me.organization_id);
        setSellerModels(orgModels);
      } catch (err) {
        console.warn('Failed to load seller models:', err);
        setSellerModels([]);
      }
    } catch (err) {
      console.warn('Failed to load placements:', err);
    }
  }, []);

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
      loadPlacements();
    }
  }, [period, authLoading, user, loadData, loadPlacements]);

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

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <VerificationRequest />
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">{tp("activePlacements")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <PromotionPurchase
              models={sellerModels}
              onPurchase={loadPlacements}
            />
            {activePlacements.length > 0 ? (
              <div className="space-y-2">
                {activePlacements.map((p) => (
                  <div
                    key={p.id}
                    className="flex items-center justify-between text-sm border rounded-lg px-3 py-2"
                  >
                    <span className="font-medium">
                      {p.placement_type.replace(/_/g, " ")}
                    </span>
                    <div className="flex items-center gap-2">
                      <Badge variant="secondary">{p.duration_days}d</Badge>
                      <span className="text-muted-foreground">
                        {new Date(p.expires_at).toLocaleDateString()}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                {tp("noActivePlacements")}
              </p>
            )}
          </CardContent>
        </Card>
      </div>

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
