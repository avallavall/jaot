"use client";

import { useTranslations } from "next-intl";
import { VersionDropdown } from "@/components/builder/VersionDropdown";

interface VersionSelectorProps {
  documentId: string;
  /** Latest committed sequence, for the "vK" badge (null = no versions yet). */
  latestSequence: number | null;
  /** Bumped on commit/restore so the dropdown refetches its cached list. */
  saveCounter: number;
  onViewAll: () => void;
  onRestore: (versionId: string) => void;
}

/**
 * The header version control: a "vK" badge + the recent-versions dropdown (reused
 * from the builder) with restore + "view all".
 */
export function VersionSelector({
  documentId,
  latestSequence,
  saveCounter,
  onViewAll,
  onRestore,
}: VersionSelectorProps) {
  const t = useTranslations("studio");

  return (
    <div className="flex items-center gap-1">
      <span className="rounded bg-muted px-1.5 py-0.5 text-xs font-medium text-muted-foreground">
        {latestSequence === null
          ? t("versionNone")
          : t("versionBadge", { sequence: latestSequence })}
      </span>
      <VersionDropdown
        documentId={documentId}
        saveCounter={saveCounter}
        onViewAll={onViewAll}
        onRestore={onRestore}
      />
    </div>
  );
}
