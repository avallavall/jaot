"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { Sparkles } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { useBuilderStore } from "@/hooks/useBuilderStore";
import { diffCanvasJson } from "@/lib/builder/diff";
import type { CanvasDiff } from "@/lib/builder/diff";
import {
  useModelProjectStore,
  useModelProjectStoreApi,
} from "../store/useModelProjectStore";
import {
  isValidSummary,
  suggestedSummary,
  detectedChanges,
  diffCategoryLabel,
} from "./commit-helpers";

interface CommitDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  workspaceId?: string;
  /** Called after a successful commit (so the header can refresh + clear the dirty flag). */
  onCommitted: () => void;
}

/**
 * The commit moment: a required "What changed?" summary + an optional "Why?" body.
 * Flushes the on-screen model into the `ModelProject` draft, then commits it as an
 * immutable version (`POST /projects/{id}/commit`) — the backend enforces the
 * required summary + content-hash dedup. The AI-suggested message is P4; here the
 * suggestion is the deterministic `diffCanvasJson` summary.
 */
export function CommitDialog({
  open,
  onOpenChange,
  projectId,
  workspaceId,
  onCommitted,
}: CommitDialogProps) {
  const t = useTranslations("studio");
  const storeApi = useModelProjectStoreApi();
  const scratchParseError = useModelProjectStore((s) => s.parseErrors.scratch ?? false);
  const dslParseError = useModelProjectStore((s) => s.parseErrors.dsl ?? false);
  const blockCommit = scratchParseError || dslParseError;
  const [summary, setSummary] = useState("");
  const [body, setBody] = useState("");
  const [diff, setDiff] = useState<CanvasDiff | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  // On open, diff the current canvas against the latest committed version for the
  // suggested message + the "detected changes" line.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setSummary("");
    setBody("");
    setDiff(null);
    const { nodes, edges } = useBuilderStore.getState();
    const current = { nodes, edges };
    api
      .listProjectVersions(projectId, { limit: 1 }, workspaceId)
      .then(async (list) => {
        if (cancelled || list.length === 0) return;
        const full = await api.getProjectVersion(projectId, list[0].id, workspaceId);
        if (cancelled) return;
        const prevCanvas = (full.canvas_json as { nodes?: unknown[]; edges?: unknown[] }) ?? {};
        setDiff(diffCanvasJson(prevCanvas, current));
      })
      .catch(() => {
        /* no prior version / fetch failed — first commit has no diff */
      });
    return () => {
      cancelled = true;
    };
  }, [open, projectId, workspaceId]);

  const suggestion = suggestedSummary(diff);
  const changes = detectedChanges(diff);


  // Flush the on-screen model into the draft (so the committed version matches it),
  // refetching the lock once on a concurrency conflict.
  const flushDraft = useCallback(async () => {
    const buildDraftBody = () => {
      const { nodes, edges } = useBuilderStore.getState();
      const st = storeApi.getState();
      return {
        model_json: st.problem as unknown as Record<string, unknown>,
        canvas_json: { nodes, edges } as unknown as Record<string, unknown>,
        // Co-version the JModel source with the model it produced. Committing inside the
        // autosave debounce would otherwise freeze a stale source into the version.
        ...(st.dslDirty ? { dsl_source: st.draftDslSource } : {}),
      };
    };
    try {
      const p = await api.updateProjectDraft(
        projectId,
        buildDraftBody(),
        storeApi.getState().lockVersion,
        workspaceId
      );
      storeApi.getState().setLockVersion(p.draft_lock_version);
    } catch (err: unknown) {
      if ((err as { status?: number })?.status !== 409) throw err;
      const latest = await api.getProject(projectId, workspaceId);
      // Re-serialize on retry — the on-screen state is the commit's truth, and a
      // stale snapshot could overwrite what a racing autosave already persisted
      const p = await api.updateProjectDraft(
        projectId,
        buildDraftBody(),
        latest.draft_lock_version,
        workspaceId
      );
      storeApi.getState().setLockVersion(p.draft_lock_version);
    }
  }, [projectId, workspaceId, storeApi]);

  const handleCommit = useCallback(async () => {
    if (!isValidSummary(summary) || blockCommit) return;
    setIsSaving(true);
    try {
      await flushDraft();
      await api.commitProjectVersion(
        projectId,
        { summary: summary.trim(), body: body.trim() || undefined },
        workspaceId
      );
      toast.success(t("versionCommitted"));
      onCommitted();
      onOpenChange(false);
    } catch {
      toast.error(t("versionCommitFailed"));
    } finally {
      setIsSaving(false);
    }
  }, [
    summary,
    body,
    blockCommit,
    projectId,
    workspaceId,
    flushDraft,
    onCommitted,
    onOpenChange,
    t,
  ]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t("versionCommitTitle")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <label
              htmlFor="commit-summary"
              className="text-xs font-medium text-muted-foreground block mb-1"
            >
              {t("versionWhatChanged")} <span className="text-destructive">*</span>
            </label>
            <Input
              id="commit-summary"
              autoFocus
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              placeholder={t("versionWhatChangedPlaceholder")}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleCommit();
              }}
            />
          </div>

          {suggestion && (
            <div className="flex items-start gap-1.5 text-xs text-muted-foreground">
              <Sparkles className="size-3.5 shrink-0 mt-0.5 text-primary" />
              <span className="min-w-0">
                {t("versionSuggested")}: <span className="italic">“{suggestion}”</span>
                <button
                  type="button"
                  className="ml-1 font-medium text-primary hover:underline"
                  onClick={() => setSummary(suggestion)}
                >
                  {t("versionUseSuggested")}
                </button>
              </span>
            </div>
          )}

          {changes.length > 0 && (
            <p className="text-xs text-muted-foreground">
              <span className="font-medium">{t("versionDetected")}:</span>{" "}
              {changes.map((c, i) => (
                <span key={c.category}>
                  {c.added > 0 && `+${c.added} `}
                  {c.removed > 0 && `−${c.removed} `}
                  {c.modified > 0 && `~${c.modified} `}
                  {diffCategoryLabel(c.category, t)}
                  {i < changes.length - 1 ? " · " : ""}
                </span>
              ))}
            </p>
          )}

          <div>
            <label
              htmlFor="commit-body"
              className="text-xs font-medium text-muted-foreground block mb-1"
            >
              {t("versionWhy")}
            </label>
            <textarea
              id="commit-body"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder={t("versionWhyPlaceholder")}
              rows={3}
              className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
            />
          </div>

          {blockCommit && (
            <p className="text-xs text-destructive">
              {scratchParseError ? t("editorBlockCommit") : t("jmodelBlockCommit")}
            </p>
          )}
        </div>

        <div className="flex justify-end gap-2 pt-1">
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            {t("versionCancel")}
          </Button>
          <Button
            size="sm"
            onClick={handleCommit}
            disabled={!isValidSummary(summary) || isSaving || blockCommit}
          >
            {isSaving ? t("versionCommitting") : t("versionCommit")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
