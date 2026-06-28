"use client";

import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { ChevronLeft, Save, Sparkles, Play, Check, Loader2, AlertCircle } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { Button } from "@/components/ui/button";
import { StudioTabBar } from "./StudioTabBar";
import { LiveStatsPanel } from "./LiveStatsPanel";
import { useModelProjectStore } from "./store/useModelProjectStore";
import type { SaveState } from "./store/createModelProjectStore";

/**
 * The persistent workspace chrome: header (model name + save state + Commit/
 * Explain/Solve), the Build/Analyze/Solve tab bar, and the live-stats rail.
 * Presentational — the model is loaded by the store provider above; this reads
 * the canonical store. P0: header actions are stubs (toast "coming soon").
 */
export function WorkspaceShell({ children }: { children: React.ReactNode }) {
  const t = useTranslations("studio");
  const name = useModelProjectStore((s) => s.name);
  const modelId = useModelProjectStore((s) => s.modelId);
  const saveState = useModelProjectStore((s) => s.saveState);

  const comingSoon = () => toast(t("comingSoon"));

  return (
    <div className="flex flex-col h-full min-h-0">
      <header className="flex items-center justify-between gap-3 border-b px-4 py-2">
        <div className="flex items-center gap-2 min-w-0">
          <Link
            href="/studio"
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ChevronLeft className="h-4 w-4" />
            {t("backToModels")}
          </Link>
          <span className="text-muted-foreground" aria-hidden="true">
            /
          </span>
          <span className="font-medium truncate">{name || t("untitled")}</span>
          <SaveIndicator state={saveState} />
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={comingSoon}>
            <Save className="h-4 w-4 mr-1" />
            {t("headerCommit")}
          </Button>
          <Button variant="outline" size="sm" onClick={comingSoon}>
            <Sparkles className="h-4 w-4 mr-1" />
            {t("headerExplain")}
          </Button>
          <Button size="sm" onClick={comingSoon}>
            <Play className="h-4 w-4 mr-1" />
            {t("headerSolve")}
          </Button>
        </div>
      </header>

      <StudioTabBar modelId={modelId} />

      <div className="flex flex-1 min-h-0 overflow-hidden">
        <div className="flex flex-1 min-w-0 flex-col overflow-hidden">{children}</div>
        <LiveStatsPanel />
      </div>
    </div>
  );
}

function SaveIndicator({ state }: { state: SaveState }) {
  const t = useTranslations("studio");
  if (state === "idle") return null;

  if (state === "saving") {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" />
        {t("saveSaving")}
      </span>
    );
  }
  if (state === "saved") {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
        <Check className="h-3 w-3" />
        {t("saveSaved")}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs text-destructive">
      <AlertCircle className="h-3 w-3" />
      {t("saveError")}
    </span>
  );
}
