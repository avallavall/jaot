"use client";

import { useTranslations } from "next-intl";

interface OriginBadgeProps {
  origin?: string;
  triggerName?: string;
}

export function OriginBadge({ origin, triggerName }: OriginBadgeProps) {
  const t = useTranslations("solve.origin");
  if (origin === "triggered") {
    return (
      <span
        className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border bg-violet-100 text-violet-800 border-violet-200 dark:bg-violet-900/30 dark:text-violet-300 dark:border-violet-700"
        title={triggerName ? t("triggerName", { name: triggerName }) : t("triggeredRun")}
      >
        {t("triggered")}
      </span>
    );
  }

  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border bg-gray-100 text-gray-700 border-gray-200 dark:bg-gray-800/40 dark:text-gray-300 dark:border-gray-700">
      {t("manual")}
    </span>
  );
}
