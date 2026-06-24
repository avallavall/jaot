"use client";

import { useTranslations } from "next-intl";
import { ShoppingCart, Coins, Percent, Wallet } from "lucide-react";
import type { EarningsSummary as EarningsSummaryType } from "@/lib/api";

interface EarningsSummaryProps {
  summary: EarningsSummaryType;
}

export function EarningsSummary({ summary }: EarningsSummaryProps) {
  const t = useTranslations("seller.earnings");

  const cards = [
    {
      label: t("totalSales"),
      value: summary.total_sales.toLocaleString(),
      icon: ShoppingCart,
      color: "text-blue-600",
      bgColor: "bg-blue-50 dark:bg-blue-950/30",
    },
    {
      label: t("totalEarned"),
      value: t("credits", { amount: summary.total_earned.toLocaleString() }),
      icon: Coins,
      color: "text-green-600",
      bgColor: "bg-green-50 dark:bg-green-950/30",
    },
    {
      label: t("commissionPaid"),
      value: t("credits", { amount: summary.total_commission.toLocaleString() }),
      icon: Percent,
      color: "text-orange-600",
      bgColor: "bg-orange-50 dark:bg-orange-950/30",
    },
    {
      label: t("withdrawableBalance"),
      value: t("credits", { amount: summary.withdrawable_balance.toLocaleString() }),
      icon: Wallet,
      color: "text-purple-600",
      bgColor: "bg-purple-50 dark:bg-purple-950/30",
    },
  ];

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {cards.map((card) => (
          <div
            key={card.label}
            className="bg-card border rounded-lg p-5"
          >
            <div className="flex items-center gap-3 mb-3">
              <div className={`p-2 rounded-lg ${card.bgColor}`}>
                <card.icon className={`h-5 w-5 ${card.color}`} />
              </div>
            </div>
            <div className="text-sm text-muted-foreground">{card.label}</div>
            <div className="text-xl font-bold mt-1">{card.value}</div>
          </div>
        ))}
      </div>
      <div className="flex justify-end">
        <span className="text-xs text-muted-foreground px-2 py-1 bg-muted/40 rounded-md">
          {t("commissionRate", { rate: (summary.commission_rate * 100).toFixed(0) })}
        </span>
      </div>
    </div>
  );
}
