"use client";

import { useTranslations } from "next-intl";
import { Play } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * The Solve lens. P0 placeholder — run configuration, results, version-aware run
 * history and the real-time "Live Solve" telemetry land in later slices.
 */
export function SolvePanel() {
  const t = useTranslations("studio");

  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-3 p-6 text-center">
      <Button disabled>
        <Play className="h-4 w-4 mr-1" />
        {t("headerSolve")}
      </Button>
      <p className="text-sm text-muted-foreground max-w-sm">
        {t("solvePlaceholder")}
      </p>
    </div>
  );
}
