"use client";

import { Card, CardContent } from "@/components/ui/card";
import { useTranslations } from "next-intl";
import { Eye, Download, Coins, TrendingUp } from "lucide-react";
import type { AnalyticsSummary } from "@/lib/types";

interface AnalyticsKPICardsProps {
  data: AnalyticsSummary;
}

export function AnalyticsKPICards({ data }: AnalyticsKPICardsProps) {
  const t = useTranslations("seller.analytics");

  const cards = [
    {
      label: t("totalViews"),
      value: data.total_views.toLocaleString(),
      icon: Eye,
      color: "text-blue-600",
      bg: "bg-blue-50",
    },
    {
      label: t("totalActivations"),
      value: data.total_activations.toLocaleString(),
      icon: Download,
      color: "text-green-600",
      bg: "bg-green-50",
    },
    {
      label: t("totalRevenue"),
      value: `${data.total_revenue.toLocaleString()} credits`,
      icon: Coins,
      color: "text-amber-600",
      bg: "bg-amber-50",
    },
    {
      label: t("conversionRate"),
      value: `${data.conversion_rate}%`,
      icon: TrendingUp,
      color: "text-purple-600",
      bg: "bg-purple-50",
    },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {cards.map((card) => (
        <Card key={card.label}>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className={`p-2 rounded-lg ${card.bg}`}>
                <card.icon className={`h-5 w-5 ${card.color}`} />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">{card.label}</p>
                <p className="text-2xl font-semibold">{card.value}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
