"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { Save } from "lucide-react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { HelpTooltip } from "@/components/ui/help-tooltip";
import { useAuth } from "@/contexts/AuthContext";
import { api } from "@/lib/api";
import { useBuilderStore } from "@/hooks/useBuilderStore";
import { serializeToOptimizationProblem } from "@/lib/builder/serializer";
import type { OptimizationProblem, ProjectVersionSummary } from "@/lib/types";
import { resolveDraftCanvas } from "../store/draft-canvas";
import { canvasCanRepresentModel, exceedsCanvasScale } from "../store/model-scale";
import {
  useModelProjectStore,
  useModelProjectStoreApi,
} from "../store/useModelProjectStore";
import { selectHasParseError } from "../store/createModelProjectStore";
import { CommitDialog } from "./CommitDialog";
import { VersionSelector } from "./VersionSelector";
import { VersionHistoryDrawer } from "./VersionHistoryDrawer";
import { uncommittedSince } from "./commit-helpers";

/**
 * All version control for the workspace header: the "vK" selector, the ambient
 * "uncommitted changes since vK" line, the Commit button (+ dialog), the full
 * history drawer, restore, and the Cmd/Ctrl+S shortcut. Backed by the first-class
 * `ModelProject` version API (`/projects/{id}/versions`).
 *
 * Concept: autosave writes silent checkpoints (the draft); a *version* is an explicit,
 * message-required milestone. Committing requires a non-empty "What changed?".
 */
export function VersionControls() {
  const t = useTranslations("studio");
  const { activeWorkspaceId } = useAuth();
  const ws = activeWorkspaceId ?? undefined;
  const modelId = useModelProjectStore((s) => s.modelId);
  const headDirty = useModelProjectStore((s) => s.headDirty);
  const scratchParseError = useModelProjectStore((s) => s.parseErrors.scratch ?? false);
  const dslParseError = useModelProjectStore((s) => s.parseErrors.dsl ?? false);
  const blockCommit = scratchParseError || dslParseError;
  const storeApi = useModelProjectStoreApi();

  const [commitOpen, setCommitOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [counter, setCounter] = useState(0);
  const [latest, setLatest] = useState<ProjectVersionSummary | null>(null);
  // The version the user asked to restore while the draft held uncommitted work.
  // Held here until they say whether to discard that work.
  const [confirmDiscard, setConfirmDiscard] = useState<string | null>(null);

  const isPersisted = !!modelId && modelId !== "new";

  // Latest committed version (for the badge + ambient line); refetched on commit/restore.
  useEffect(() => {
    if (!isPersisted) return;
    let cancelled = false;
    api
      .listProjectVersions(modelId, { limit: 1 }, ws)
      .then((list) => {
        if (!cancelled) setLatest(list[0] ?? null);
      })
      .catch(() => {
        /* versions are non-critical */
      });
    return () => {
      cancelled = true;
    };
  }, [modelId, ws, counter, isPersisted]);

  // Cmd/Ctrl+S opens the commit dialog — but not while typing in a field or the editor.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== "s") return;
      const el = document.activeElement as HTMLElement | null;
      const tag = el?.tagName.toLowerCase();
      if (tag === "input" || tag === "textarea" || el?.isContentEditable) return;
      e.preventDefault();
      // Don't open the commit dialog over a model whose Editor/JModel text doesn't parse.
      if (isPersisted && !selectHasParseError(storeApi.getState())) setCommitOpen(true);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isPersisted, storeApi]);

  const handleCommitted = useCallback(() => {
    storeApi.getState().markCommitted();
    setCounter((c) => c + 1);
  }, [storeApi]);

  const handleRestore = useCallback(
    async (versionId: string, discardDraft = false) => {
      try {
        // Checks the version out into the draft (history untouched). The backend
        // answers 409 when the draft holds uncommitted work, precisely so the
        // caller can ask; this used to pass discard_draft=true always, so the
        // question was answered for the user and their work went with no warning.
        // Every COMMITTED version stays recoverable — an uncommitted draft is not
        // one, and that is exactly what was being thrown away.
        const project = await api.restoreProjectVersion(modelId, versionId, discardDraft, ws);
        const modelJson = (project.draft_model_json ?? null) as OptimizationProblem | null;
        // Same canvas-withheld gate as the provider's load: a version too large
        // for the canvas OR not exactly representable on it hydrates the
        // canonical model from model_json directly — a partial node view must
        // never become the model (serializing it back would corrupt the restore).
        if (
          modelJson &&
          (exceedsCanvasScale(modelJson) || !canvasCanRepresentModel(modelJson))
        ) {
          storeApi.getState().setCanvasDisabled(true);
          useBuilderStore.getState().reset();
          useBuilderStore.setState({ documentId: project.id, documentName: project.name });
          storeApi.getState().hydrate(modelJson, project.name);
        } else {
          // Prefer the snapshot's canvas when it faithfully denotes the model
          // (preserves node positions); resolveDraftCanvas discards a stale or
          // degenerate snapshot canvas and re-derives from the model instead.
          const { nodes, edges } = resolveDraftCanvas(
            project.draft_canvas_json as { nodes?: unknown[]; edges?: unknown[] } | null,
            modelJson
          );
          useBuilderStore.getState().setDocument(project.id, project.name, nodes, edges);
          storeApi.getState().setCanvasDisabled(false);
          storeApi
            .getState()
            .hydrate(serializeToOptimizationProblem(nodes, edges), project.name);
        }
        // Rehydrate the JModel source to the restored version's — without this the
        // pre-restore source lingers and the next autosave pushes it back, silently
        // reverting the DSL half of the restore.
        storeApi.getState().setDraftDslSource(project.draft_dsl_source ?? "");
        storeApi.getState().setLockVersion(project.draft_lock_version);
        setCounter((c) => c + 1);
        setHistoryOpen(false);
        setConfirmDiscard(null);
        toast.success(t("versionRestored"));
      } catch (err: unknown) {
        if ((err as { status?: number })?.status === 409) {
          setConfirmDiscard(versionId);
          return;
        }
        toast.error(t("versionRestoreFailed"));
      }
    },
    [modelId, ws, storeApi, t]
  );

  if (!isPersisted) return null;

  const unc = uncommittedSince(headDirty, latest?.sequence ?? null);

  return (
    <div className="flex items-center gap-2">
      {unc.show && (
        <span className="hidden md:inline text-xs text-muted-foreground">
          {unc.sinceSequence === null
            ? t("versionUncommittedNew")
            : t("versionUncommittedSince", { sequence: unc.sinceSequence })}
        </span>
      )}

      <VersionSelector
        latestSequence={latest?.sequence ?? null}
        onViewAll={() => setHistoryOpen(true)}
      />

      <Button
        variant="outline"
        size="sm"
        onClick={() => setCommitOpen(true)}
        disabled={blockCommit}
        title={
          blockCommit
            ? scratchParseError
              ? t("editorBlockCommit")
              : t("jmodelBlockCommit")
            : undefined
        }
      >
        <Save className="h-4 w-4 mr-1" />
        {t("headerCommit")}
      </Button>

      <HelpTooltip content={t("helpTooltips.commit")} side="bottom" />

      <CommitDialog
        open={commitOpen}
        onOpenChange={setCommitOpen}
        projectId={modelId}
        workspaceId={ws}
        onCommitted={handleCommitted}
      />
      <VersionHistoryDrawer
        projectId={modelId}
        isOpen={historyOpen}
        refreshKey={counter}
        onClose={() => setHistoryOpen(false)}
        onRestore={handleRestore}
      />

      <AlertDialog
        open={confirmDiscard !== null}
        onOpenChange={(open) => !open && setConfirmDiscard(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("versionRestoreDiscardTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("versionRestoreDiscardBody")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("versionRestoreDiscardCancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => confirmDiscard && void handleRestore(confirmDiscard, true)}
              data-testid="studio-version-restore-discard-confirm"
              className="bg-destructive text-white hover:bg-destructive/90"
            >
              {t("versionRestoreDiscardConfirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
