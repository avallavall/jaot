"use client";

import { useTranslations } from "next-intl";
import { History } from "lucide-react";
import { Button } from "@/components/ui/button";

interface VersionSelectorProps {
  /** Latest committed sequence, for the "vK" badge (null = no versions yet). */
  latestSequence: number | null;
  /** Open the full version history drawer. */
  onViewAll: () => void;
}

/**
 * The header version control: a "vK" badge + a button that opens the full version
 * history (list / diff / restore). The history drawer is the project's version
 * timeline, backed by the `/projects/{id}/versions` API.
 */
export function VersionSelector({ latestSequence, onViewAll }: VersionSelectorProps) {
  const t = useTranslations("studio");

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={onViewAll}
      className="gap-1.5 text-muted-foreground"
      title={t("versionHistoryTitle")}
    >
      <History className="h-4 w-4" />
      <span className="rounded bg-muted px-1.5 py-0.5 text-xs font-medium">
        {latestSequence === null
          ? t("versionNone")
          : t("versionBadge", { sequence: latestSequence })}
      </span>
    </Button>
  );
}
