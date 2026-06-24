"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { api } from "@/lib/api";
import type {
  EarningsSummary as EarningsSummaryType,
  SaleRecord,
  WithdrawalSchedule,
} from "@/lib/api";
import { EarningsSummary } from "@/components/seller/EarningsSummary";
import { SalesHistoryTable } from "@/components/seller/SalesHistoryTable";
import { PayoutConfig } from "@/components/seller/PayoutConfig";
import { useAuth } from "@/contexts/AuthContext";

export default function SellerEarningsPage() {
  const t = useTranslations("seller.earnings");
  const { user, isLoading: authLoading } = useAuth();

  const [summary, setSummary] = useState<EarningsSummaryType | null>(null);
  const [sales, setSales] = useState<SaleRecord[]>([]);
  const [salesTotal, setSalesTotal] = useState(0);
  const [salesPage, setSalesPage] = useState(1);
  const [schedules, setSchedules] = useState<WithdrawalSchedule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const PAGE_SIZE = 20;

  const loadSummary = useCallback(async () => {
    try {
      const data = await api.getSellerEarningsSummary();
      setSummary(data);
    } catch (err) {
      console.warn('Failed to load earnings summary:', err);
    }
  }, []);

  const loadSales = useCallback(async (page: number) => {
    try {
      const data = await api.getSellerSalesHistory({
        page,
        page_size: PAGE_SIZE,
      });
      setSales(data.items);
      setSalesTotal(data.total);
      setSalesPage(data.page);
    } catch {
      setSales([]);
      setSalesTotal(0);
    }
  }, []);

  const loadSchedules = useCallback(async () => {
    try {
      const data = await api.getWithdrawalSchedules();
      setSchedules(data || []);
    } catch {
      setSchedules([]);
    }
  }, []);

  useEffect(() => {
    if (authLoading) return;
    if (!user) return;

    const loadAll = async () => {
      setLoading(true);
      setError(null);
      try {
        await Promise.all([loadSummary(), loadSales(1), loadSchedules()]);
      } catch {
        setError(t("failedToLoad"));
      } finally {
        setLoading(false);
      }
    };

    loadAll();
  }, [user, authLoading, loadSummary, loadSales, loadSchedules, t]);

  const handlePageChange = (page: number) => {
    loadSales(page);
  };

  const handleScheduleCreate = async (data: {
    frequency: string;
    amount_type: string;
    amount_value?: number;
    min_threshold: number;
  }) => {
    await api.createWithdrawalSchedule(data);
    await loadSchedules();
  };

  const handleScheduleDelete = async (id: string) => {
    await api.deleteWithdrawalSchedule(id);
    await loadSchedules();
  };

  if (authLoading || loading) {
    return (
      <div className="container mx-auto px-4 py-8 max-w-5xl" aria-busy="true">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-muted rounded w-1/3"></div>
          <div className="h-32 bg-muted rounded"></div>
          <div className="h-64 bg-muted rounded"></div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container mx-auto px-4 py-8 max-w-5xl">
        <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-lg p-6 text-center">
          <p className="text-red-600 dark:text-red-400">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8 max-w-5xl">
      <div className="mb-6">
        <Link
          href="/workspace/credits"
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          {t("backToCredits")}
        </Link>
      </div>

      <h1 className="text-3xl font-bold text-foreground mb-8">{t("title")}</h1>

      {summary && (
        <div className="mb-8">
          <EarningsSummary summary={summary} />
        </div>
      )}

      <div className="mb-8">
        <h2 className="text-lg font-semibold mb-4">{t("salesHistory")}</h2>
        <SalesHistoryTable
          sales={sales}
          total={salesTotal}
          page={salesPage}
          pageSize={PAGE_SIZE}
          onPageChange={handlePageChange}
        />
      </div>

      <div className="mb-8">
        <PayoutConfig
          schedules={schedules}
          creditsEarned={summary?.withdrawable_balance ?? 0}
          onScheduleCreate={handleScheduleCreate}
          onScheduleDelete={handleScheduleDelete}
        />
      </div>
    </div>
  );
}
