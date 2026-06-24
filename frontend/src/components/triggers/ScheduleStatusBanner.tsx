"use client";

import { useTranslations } from "next-intl";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ScheduleStatusBannerProps {
  consecutiveFailures: number;
  isEnabled: boolean;
  onReEnable: () => void;
  loading?: boolean;
}

export function ScheduleStatusBanner({
  consecutiveFailures,
  isEnabled,
  onReEnable,
  loading,
}: ScheduleStatusBannerProps) {
  const t = useTranslations("triggers.schedule");

  if (consecutiveFailures < 5 || isEnabled) return null;

  return (
    <div className="flex items-start gap-3 p-4 rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-800">
      <AlertTriangle className="w-5 h-5 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
      <div className="flex-1">
        <h4 className="text-sm font-semibold text-amber-800 dark:text-amber-300">
          {t("autoDisabledTitle")}
        </h4>
        <p className="text-sm text-amber-700 dark:text-amber-400 mt-0.5">
          {t("autoDisabledDescription", { count: consecutiveFailures })}
        </p>
        <Button
          variant="outline"
          size="sm"
          className="mt-2"
          onClick={onReEnable}
          disabled={loading}
        >
          {t("reenableSchedule")}
        </Button>
      </div>
    </div>
  );
}
