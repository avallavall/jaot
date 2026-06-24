"use client";

import { useTranslations } from "next-intl";
import { formatNextRun } from "@/lib/cron-utils";
import { Calendar } from "lucide-react";

interface NextRunsPreviewProps {
  nextRuns: string[];
  locale: string;
}

export function NextRunsPreview({ nextRuns, locale }: NextRunsPreviewProps) {
  const t = useTranslations("triggers.schedule");

  if (nextRuns.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">{t("noUpcomingRuns")}</p>
    );
  }

  return (
    <div className="space-y-1.5">
      <h4 className="text-sm font-medium text-muted-foreground">
        {t("upcomingRuns")}
      </h4>
      <ul className="space-y-1">
        {nextRuns.slice(0, 5).map((run, i) => {
          const { relative, absolute } = formatNextRun(run, locale);
          return (
            <li key={i} className="flex items-center gap-2 text-sm">
              <Calendar className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
              <span>
                {relative}{" "}
                <span className="text-muted-foreground">({absolute})</span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
