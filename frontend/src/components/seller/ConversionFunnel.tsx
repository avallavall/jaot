"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useTranslations } from "next-intl";
import type { ConversionFunnel as ConversionFunnelType } from "@/lib/types";

interface ConversionFunnelProps {
  data: ConversionFunnelType;
}

export function ConversionFunnel({ data }: ConversionFunnelProps) {
  const t = useTranslations("seller.analytics");

  const stages = [
    {
      label: t("funnelImpressions"),
      value: data.impressions,
      pct: 100,
      color: "bg-blue-500",
    },
    {
      label: t("funnelViews"),
      value: data.views,
      pct: data.impressions > 0 ? (data.views / data.impressions) * 100 : 0,
      color: "bg-indigo-500",
    },
    {
      label: t("funnelActivations"),
      value: data.activations,
      pct: data.views > 0 ? (data.activations / data.views) * 100 : 0,
      color: "bg-green-500",
    },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-medium">
          {t("conversionFunnel")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {stages.map((stage, i) => (
            <div key={stage.label}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm font-medium">{stage.label}</span>
                <span className="text-sm text-muted-foreground">
                  {stage.value.toLocaleString()}
                  {i > 0 && (
                    <span className="ml-1 text-xs">
                      ({stage.pct.toFixed(1)}%)
                    </span>
                  )}
                </span>
              </div>
              <div className="h-3 bg-muted rounded-full overflow-hidden">
                <div
                  className={`h-full ${stage.color} rounded-full transition-all`}
                  style={{
                    width: `${stages[0].value > 0 ? (stage.value / stages[0].value) * 100 : 0}%`,
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
