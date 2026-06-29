"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { ChevronLeft, Sparkles, Play, Check, Loader2, AlertCircle } from "lucide-react";
import { Link, useRouter } from "@/i18n/navigation";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { StudioTabBar } from "./StudioTabBar";
import { LiveStatsPanel } from "./LiveStatsPanel";
import { VersionControls } from "./versioning/VersionControls";
import { useModelProjectStore } from "./store/useModelProjectStore";
import type { SaveState } from "./store/createModelProjectStore";
import { commitRename } from "./rename";

/**
 * The persistent workspace chrome: header (editable model name + save state +
 * Commit/Explain/Solve), the Build/Analyze/Solve tab bar, and the live-stats rail.
 * Presentational — the model is loaded by the store provider above; this reads the
 * canonical store. "Explain model" is disabled until the AI tab provides a project
 * conversation (a later slice) — shown as a clearly-disabled "soon" control, not a
 * dead button that toasts.
 */
export function WorkspaceShell({ children }: { children: React.ReactNode }) {
  const t = useTranslations("studio");
  const router = useRouter();
  const name = useModelProjectStore((s) => s.name);
  const modelId = useModelProjectStore((s) => s.modelId);
  const saveState = useModelProjectStore((s) => s.saveState);
  const setName = useModelProjectStore((s) => s.setName);

  const [draft, setDraft] = useState(name);
  // Keep the input in sync when the store name changes elsewhere (load / restore).
  useEffect(() => {
    setDraft(name);
  }, [name]);

  const goToSolve = () => router.push(`/studio/${modelId}/solve`);

  const onRenameBlur = () =>
    commitRename({
      modelId,
      next: draft,
      current: name,
      setName,
      update: (id, body) => api.updateProject(id, body),
      onError: () => {
        setDraft(name);
        toast.error(t("renameError"));
      },
    });

  return (
    <div className="flex flex-col h-full min-h-0">
      <header className="flex items-center justify-between gap-3 border-b px-4 py-2">
        <div className="flex items-center gap-2 min-w-0">
          <Link
            href="/studio"
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground shrink-0"
          >
            <ChevronLeft className="h-4 w-4" />
            {t("backToModels")}
          </Link>
          <span className="text-muted-foreground shrink-0" aria-hidden="true">
            /
          </span>
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={onRenameBlur}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
              if (e.key === "Escape") {
                setDraft(name);
                (e.target as HTMLInputElement).blur();
              }
            }}
            placeholder={t("namePlaceholder")}
            aria-label={t("namePlaceholder")}
            className="min-w-0 max-w-[18rem] truncate rounded border border-transparent bg-transparent px-1 -mx-1 text-sm font-medium hover:border-input focus:border-input focus:outline-none focus:ring-1 focus:ring-ring"
          />
          <SaveIndicator state={saveState} />
        </div>
        <div className="flex items-center gap-2">
          <VersionControls />
          <Button
            variant="outline"
            size="sm"
            disabled
            title={t("comingSoon")}
            aria-label={`${t("headerExplain")} — ${t("comingSoon")}`}
          >
            <Sparkles className="h-4 w-4 mr-1" />
            {t("headerExplain")}
          </Button>
          <Button size="sm" onClick={goToSolve}>
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
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground shrink-0">
        <Loader2 className="h-3 w-3 animate-spin" />
        {t("saveSaving")}
      </span>
    );
  }
  if (state === "saved") {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground shrink-0">
        <Check className="h-3 w-3" />
        {t("saveSaved")}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs text-destructive shrink-0">
      <AlertCircle className="h-3 w-3" />
      {t("saveError")}
    </span>
  );
}
