"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { api, CreditTransaction } from "@/lib/api";

// Extended balance type — API returns the three-pool credit model. In the free,
// collaborative deployment credits are a usage quota (no money in or out), so we
// only surface the total balance and the renewable monthly allowance.
interface CreditBalance {
  credits_balance: number;
  credits_subscription: number;
  credits_purchased: number;
  credits_earned: number;
  credits_used_month?: number;
  plan?: string;
  monthly_limit?: number;
}
import { ConceptTooltip } from "@/components/ui/concept-tooltip";
import { EmptyState } from "@/components/guidance/EmptyState";
import { useTranslations } from "next-intl";
import { useCommonLabels } from "@/hooks/useCommonLabels";
import { Coins } from "lucide-react";

export default function CreditsPage() {
  const t = useTranslations("workspace.credits");
  const { transactionTypeLabel } = useCommonLabels();

  const [balance, setBalance] = useState<CreditBalance | null>(null);
  const [transactions, setTransactions] = useState<CreditTransaction[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const balanceData = await (api.getCreditBalance() as Promise<CreditBalance>).catch(() => null);
      if (balanceData) setBalance(balanceData);

      try {
        const txData = await api.getCreditTransactions({ limit: 20 });
        setTransactions(txData || []);
      } catch {
        setTransactions([]);
      }
    } finally {
      setLoading(false);
    }
  };

  const getTxTypeColor = (type: string) => {
    if (type.includes("earning") || type === "purchase" || type === "bonus" || type === "refund") {
      return "text-green-600";
    }
    return "text-red-600";
  };

  if (loading) {
    return (
      <div className="container mx-auto px-4 py-8" aria-busy="true">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-muted rounded w-1/3"></div>
          <div className="h-64 bg-muted rounded"></div>
        </div>
        <div aria-live="polite" className="sr-only">{t("loadingCredits")}</div>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8 max-w-5xl">
      <div className="mb-6">
        <Link href="/workspace" className="text-sm text-muted-foreground hover:text-foreground">
          {t("backToWorkspace")}
        </Link>
      </div>

      <h1 className="text-3xl font-bold text-foreground mb-8">{t("title")}</h1>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        <div className="bg-card border rounded-lg p-6">
          <div className="text-sm text-muted-foreground mb-1">{t("totalBalance")}</div>
          <div className="text-4xl font-bold text-primary">
            {balance?.credits_balance.toLocaleString()} <span className="text-xl">{t("credits")}</span>
          </div>
        </div>

        <div className="bg-card border rounded-lg p-6">
          <div className="text-sm text-muted-foreground mb-1">{t("subscriptionCredits")}</div>
          <div className="text-4xl font-bold text-foreground">
            {(balance?.credits_subscription ?? 0).toLocaleString()}
          </div>
          <div className="text-xs text-muted-foreground mt-2">
            {t("subscriptionCreditsNote")}
          </div>
        </div>
      </div>

      <div className="bg-card border rounded-lg p-6 mb-8">
        <h2 className="text-lg font-semibold mb-3">{t("howCalculated")}</h2>
        <p className="text-sm text-muted-foreground mb-3">
          {t("calculatedDescriptionSqrt")}
        </p>
        <div className="flex flex-wrap gap-3 text-sm">
          <span className="px-3 py-1.5 bg-muted/40 rounded-md">
            <ConceptTooltip termKey="base-cost">{t("baseCost")}</ConceptTooltip>
          </span>
          <span className="text-muted-foreground self-center">+</span>
          <span className="px-3 py-1.5 bg-muted/40 rounded-md">
            <ConceptTooltip termKey="variable-cost">{"sqrt(vars)"}</ConceptTooltip>
          </span>
          <span className="text-muted-foreground self-center">+</span>
          <span className="px-3 py-1.5 bg-muted/40 rounded-md">
            <ConceptTooltip termKey="integer-penalty">{"sqrt(MIP)"}</ConceptTooltip>
          </span>
          <span className="text-muted-foreground self-center">+</span>
          <span className="px-3 py-1.5 bg-muted/40 rounded-md">
            <ConceptTooltip termKey="constraint-cost">{"sqrt(constraints)"}</ConceptTooltip>
          </span>
          <span className="text-muted-foreground self-center">+</span>
          <span className="px-3 py-1.5 bg-muted/40 rounded-md">
            <ConceptTooltip termKey="time-bonus">{t("timeBonus")}</ConceptTooltip>
          </span>
        </div>
        <div className="mt-3 px-3 py-2 bg-primary/5 border border-primary/20 rounded-md text-sm text-primary">
          {t("maxCreditsNote")}
        </div>
      </div>

      <div className="bg-card border rounded-lg p-6">
        <h2 className="text-lg font-semibold mb-4">{t("transactionHistory")}</h2>
        {transactions.length > 0 ? (
          <div className="space-y-2">
            {transactions.map((tx) => (
              <div key={tx.id} className="flex items-center justify-between p-3 border-b last:border-0">
                <div>
                  <div className="font-medium">{tx.description || t("creditTransaction")}</div>
                  <div className="text-xs text-muted-foreground">
                    {new Date(tx.created_at).toLocaleString()} · {transactionTypeLabel(tx.transaction_type || "purchase")}
                  </div>
                </div>
                <div className={`font-mono font-medium ${getTxTypeColor(tx.transaction_type || "purchase")}`}>
                  {tx.credits_amount != null ? (
                    <>
                      {tx.credits_amount > 0 ? "+" : ""}{tx.credits_amount.toLocaleString()}
                    </>
                  ) : (
                    <span className="text-muted-foreground">-</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={<Coins className="h-12 w-12" />}
            title={t("noActivityTitle")}
            description={t("noActivityDescription")}
            expertDescription={t("noActivityExpert")}
            actionLabel={t("viewPricing")}
            actionHref="/marketplace"
          />
        )}
      </div>
    </div>
  );
}
