"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useFormatter, useNow, useTranslations } from "next-intl";
import { ChevronLeft, Sparkles, Play, Check, Loader2, AlertCircle } from "lucide-react";
import { Link, useRouter } from "@/i18n/navigation";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { apiDate } from "@/lib/dates";
import { StudioTabBar } from "./StudioTabBar";
import { LiveStatsPanel } from "./LiveStatsPanel";
import { VersionControls } from "./versioning/VersionControls";
import { useModelProjectStore, useModelProjectStoreApi } from "./store/useModelProjectStore";
import type { SaveState } from "./store/createModelProjectStore";
import { commitRename } from "./rename";

/**
 * The persistent workspace chrome: header (editable model name + save state +
 * Commit/Explain/Solve), the Build/Analyze/Solve tab bar, and the live-stats rail.
 * Presentational — the model is loaded by the store provider above; this reads the
 * canonical store. "Explain model" jumps to the Analyze lens, where the grounded LLM
 * explanation streams (mirrors how "Solve" jumps to the Solve lens).
 */
export function WorkspaceShell({ children }: { children: React.ReactNode }) {
  const t = useTranslations("studio");
  const router = useRouter();
  const name = useModelProjectStore((s) => s.name);
  const modelId = useModelProjectStore((s) => s.modelId);
  const saveState = useModelProjectStore((s) => s.saveState);
  const scratchParseError = useModelProjectStore((s) => s.parseErrors.scratch ?? false);
  const dslParseError = useModelProjectStore((s) => s.parseErrors.dsl ?? false);
  const setName = useModelProjectStore((s) => s.setName);
  const storeApi = useModelProjectStoreApi();
  const blockSolve = scratchParseError || dslParseError;

  const nameInputRef = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState(name);
  // Keep the input in sync when the store name changes elsewhere (load / restore) —
  // but NEVER clobber what the user is actively typing. A late hydrate landing on top
  // of an in-progress rename would otherwise silently discard the new name (and, since
  // the reverted draft then equals the stored name, the blur commits nothing).
  useEffect(() => {
    // One-way sync of the external store name (load/restore) into the editable draft,
    // guarded so a late hydrate never overwrites an in-progress rename (focused input).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (document.activeElement !== nameInputRef.current) setDraft(name);
  }, [name]);

  const goToSolve = () => router.push(`/studio/${modelId}/solve`);

  const onRenameBlur = () =>
    commitRename({
      modelId,
      next: draft,
      current: name,
      setName,
      getName: () => storeApi.getState().name,
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
            ref={nameInputRef}
            data-testid="studio-name-input"
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
          <SolveStatusIndicator onGoToSolve={goToSolve} />
          <VersionControls />
          <Button
            variant="outline"
            size="sm"
            data-testid="studio-header-explain"
            onClick={() => router.push(`/studio/${modelId}/analyze`)}
          >
            <Sparkles className="h-4 w-4 mr-1" />
            {t("headerExplain")}
          </Button>
          <Button
            size="sm"
            data-testid="studio-header-solve"
            onClick={goToSolve}
            disabled={blockSolve}
            title={
              blockSolve
                ? scratchParseError
                  ? t("editorBlockSolve")
                  : t("jmodelBlockSolve")
                : undefined
            }
          >
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

/**
 * Ambient "this model is solving" pill, visible from ANY tab (the solve session
 * lives in the provider store, shared by Build/Analyze/Solve). Derived from the
 * server on open, so a solve started hours ago — or in another tab/device —
 * still shows here with how long it's been running. Click to jump to the live view.
 */
function SolveStatusIndicator({ onGoToSolve }: { onGoToSolve: () => void }) {
  const t = useTranslations("studio");
  const format = useFormatter();
  // Tick every 15s so "started Xs/Xm ago" stays fresh for the common
  // sub-minute solve, not just long ones. `now` is also passed to
  // relativeTime so next-intl doesn't warn about a missing reference time
  // (ENVIRONMENT_FALLBACK).
  const now = useNow({ updateInterval: 15_000 });
  const status = useModelProjectStore((s) => s.solveSession.status);
  const startedAt = useModelProjectStore((s) => s.solveSession.startedAt);
  if (status !== "running") return null;

  // Clamp the start to `now` so a server clock slightly ahead of this
  // 15s-frozen snapshot can never render a FUTURE label ("dentro de 2 s")
  // — a solve in progress is always in the past.
  const started = startedAt
    ? new Date(Math.min(apiDate(startedAt).getTime(), now.getTime()))
    : null;
  const label = started
    ? t("solvingSince", { when: format.relativeTime(started, now) })
    : t("solveRunning");
  return (
    <button
      type="button"
      onClick={onGoToSolve}
      data-testid="studio-solving-indicator"
      className="inline-flex items-center gap-1.5 rounded-full border border-amber-300 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-800 hover:bg-amber-100 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200 dark:hover:bg-amber-900"
    >
      <Loader2 className="h-3 w-3 animate-spin" />
      {label}
    </button>
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
      <span
        data-testid="studio-saved"
        className="inline-flex items-center gap-1 text-xs text-muted-foreground shrink-0"
      >
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
