"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { OnboardingStep } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CheckCircle2, Circle } from "lucide-react";

export function OnboardingChecklist() {
  const t = useTranslations("seller.onboarding");
  const router = useRouter();
  const [steps, setSteps] = useState<OnboardingStep[]>([]);
  const [allComplete, setAllComplete] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getOnboardingStatus()
      .then((res) => {
        setSteps(res.steps);
        setAllComplete(res.all_complete);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  // Auto-hide when all steps complete
  if (loading || allComplete) return null;

  const completedCount = steps.filter((s) => s.completed).length;
  const totalCount = steps.length;
  const progressPercent = totalCount > 0 ? (completedCount / totalCount) * 100 : 0;

  const stepLabel = (key: string): string => {
    const map: Record<string, string> = {
      complete_profile: t("completeProfile"),
      publish_model: t("publishModel"),
      add_rich_media: t("addRichMedia"),
      setup_payouts: t("setupPayouts"),
    };
    return map[key] ?? key;
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{t("title")}</CardTitle>
        <p className="text-sm text-muted-foreground">{t("description")}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>{t("progressLabel")}</span>
            <span>
              {t("stepsComplete", {
                completed: completedCount,
                total: totalCount,
              })}
            </span>
          </div>
          <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
            <div
              className="h-full rounded-full bg-primary transition-all duration-300"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>

        <div className="space-y-2">
          {steps.map((step) => (
            <button
              key={step.key}
              type="button"
              onClick={() => router.push(step.link)}
              className="flex items-center gap-3 w-full text-left rounded-lg px-3 py-2 hover:bg-muted/50 transition-colors"
            >
              {step.completed ? (
                <CheckCircle2 className="w-5 h-5 text-green-500 flex-shrink-0" />
              ) : (
                <Circle className="w-5 h-5 text-muted-foreground flex-shrink-0" />
              )}
              <span
                className={`text-sm ${
                  step.completed
                    ? "text-muted-foreground line-through"
                    : "text-foreground"
                }`}
              >
                {stepLabel(step.key)}
              </span>
            </button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
