"use client";

import { useTranslations } from "next-intl";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { FunnelStep } from "./analytics-types";
import { formatEventType } from "./analytics-helpers";

interface AnalyticsFunnelProps {
  steps: FunnelStep[];
}

export function AnalyticsFunnel({ steps }: AnalyticsFunnelProps) {
  const t = useTranslations("admin.featureAnalytics");

  if (steps.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("conversionFunnel")}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-center text-muted-foreground py-8">
            {t("noEvents")}
          </p>
        </CardContent>
      </Card>
    );
  }

  const maxVal = steps[0]?.value || 1;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("conversionFunnel")}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-1">
          {steps.map((step, i) => {
            const widthPct =
              maxVal > 0 ? Math.max((step.value / maxVal) * 100, 8) : 8;
            const prevValue = i > 0 ? steps[i - 1].value : null;
            const dropOff =
              prevValue && prevValue > 0
                ? ((1 - step.value / prevValue) * 100).toFixed(0)
                : null;
            const convRate =
              prevValue && prevValue > 0
                ? ((step.value / prevValue) * 100).toFixed(0)
                : null;

            const ghostWidthPct =
              step.prev_value != null && maxVal > 0
                ? Math.max((step.prev_value / maxVal) * 100, 8)
                : null;

            return (
              <div key={step.name}>
                {dropOff !== null && (
                  <div className="text-xs text-muted-foreground py-1 pl-4">
                    ↓ {t("funnelStep", { conversion: convRate ?? "0", dropOff })}
                  </div>
                )}
                <div className="flex items-center gap-3">
                  <span className="text-sm font-medium w-[160px] text-right shrink-0">
                    {formatEventType(step.name, t)}
                  </span>
                  <div className="flex-1 relative">
                    {ghostWidthPct !== null && (
                      <div
                        className="absolute top-0 left-0 h-10 rounded-lg"
                        style={{
                          width: `${ghostWidthPct}%`,
                          backgroundColor: step.fill,
                          opacity: 0.2,
                          minWidth: "60px",
                        }}
                      />
                    )}
                    <div
                      className="h-10 rounded-lg flex items-center px-3 transition-all relative"
                      style={{
                        width: `${widthPct}%`,
                        backgroundColor: step.fill,
                        minWidth: "60px",
                      }}
                    >
                      <span className="text-white font-bold text-sm drop-shadow-sm">
                        {t("funnelUsers", { count: step.value })}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
