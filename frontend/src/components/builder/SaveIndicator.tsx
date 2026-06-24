"use client";

import { useEffect, useState } from "react";
import { Loader2, Check, AlertCircle, Circle } from "lucide-react";
import { useTranslations } from "next-intl";
import type { SaveState } from "@/hooks/useSaveIndicator";

interface SaveIndicatorProps {
  state: SaveState;
  lastSavedAt: number | null;
}

/**
 * Computes a human-readable relative time string like "5s ago", "2m ago".
 * Returns null when no save has occurred or the interval is too small.
 */
function useRelativeTime(lastSavedAt: number | null): string | null {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (lastSavedAt === null) return;

    // Tick every 10 seconds to update the relative timestamp
    const interval = setInterval(() => {
      setNow(Date.now());
    }, 10_000);

    return () => clearInterval(interval);
  }, [lastSavedAt]);

  if (lastSavedAt === null) return null;

  const diffMs = now - lastSavedAt;
  const diffSec = Math.floor(diffMs / 1000);

  if (diffSec < 5) return null; // too recent — "Saved" label is still showing
  if (diffSec < 60) return `${diffSec}s`;

  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m`;

  const diffHr = Math.floor(diffMin / 60);
  return `${diffHr}h`;
}

export function SaveIndicator({ state, lastSavedAt }: SaveIndicatorProps) {
  const t = useTranslations("builder.toolbar");
  const relativeTime = useRelativeTime(lastSavedAt);

  // Idle state with a timestamp
  if (state === "idle" && relativeTime) {
    return (
      <span className="flex items-center gap-1 text-xs text-muted-foreground select-none">
        <Circle className="h-2.5 w-2.5 fill-muted-foreground/40 stroke-none" />
        {t("lastSaved", { time: relativeTime })}
      </span>
    );
  }

  // Idle state with no timestamp (never saved, or just loaded)
  if (state === "idle") {
    return null;
  }

  if (state === "saving") {
    return (
      <span className="flex items-center gap-1 text-xs text-muted-foreground select-none">
        <Loader2 className="h-3 w-3 animate-spin" />
        {t("savingIndicator")}
      </span>
    );
  }

  if (state === "saved") {
    return (
      <span className="flex items-center gap-1 text-xs text-[var(--health-valid)] select-none">
        <Check className="h-3 w-3" />
        {t("savedIndicator")}
      </span>
    );
  }

  if (state === "unsaved") {
    return (
      <span className="flex items-center gap-1 text-xs text-muted-foreground select-none">
        <Circle className="h-2.5 w-2.5 fill-[var(--health-warning)] stroke-none" />
        {t("unsavedChanges")}
      </span>
    );
  }

  if (state === "error") {
    return (
      <span className="flex items-center gap-1 text-xs text-destructive select-none">
        <AlertCircle className="h-3 w-3" />
        {t("saveError")}
      </span>
    );
  }

  return null;
}
