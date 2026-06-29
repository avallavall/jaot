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
  isValidSummary,
  suggestedSummary,
  detectedChanges,
  type DiffCategory,
} from "./commit-helpers";

interface CommitDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  documentId: string;
  workspaceId?: string;
  /** Called after a successful commit (so the header can refresh + clear the dirty flag). */
  onCommitted: () => void;
}

/**
 * The commit moment: a required "What changed?" summary + an optional "Why?" body.
 * Reuses the builder version API — `createVersion` snapshots the canvas, then
 * `promoteVersion` attaches the message (the first-class `commit_summary` field lands
 * with the ModelProject backend in P1). The AI-suggested message is P4; here the
 * suggestion is the deterministic `diffCanvasJson` summary.
 */
export function CommitDialog({
  open,
  onOpenChange,
  documentId,
  workspaceId,
  onCommitted,
}: CommitDialogProps) {
  const t = useTranslations("studio");
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
      .listVersions(documentId, { limit: 1 }, workspaceId)
      .then(async (list) => {
        if (cancelled || list.length === 0) return;
        const full = await api.getVersion(documentId, list[0].id, workspaceId);
        if (cancelled) return;
        const prevCanvas = full.canvas_json as { nodes?: unknown[]; edges?: unknown[] };
        setDiff(diffCanvasJson(prevCanvas, current));
      })
      .catch(() => {
        /* no prior version / fetch failed — first commit has no diff */
      });
    return () => {
      cancelled = true;
    };
  }, [open, documentId, workspaceId]);

  const suggestion = suggestedSummary(diff);
  const changes = detectedChanges(diff);

  const categoryLabel = (category: DiffCategory): string => {
    switch (category) {
      case "variable":
        return t("versionCatVariable");
      case "constraint":
        return t("versionCatConstraint");
      case "objective":
        return t("versionCatObjective");
      case "link":
        return t("versionCatLink");
    }
  };

  const handleCommit = useCallback(async () => {
    if (!isValidSummary(summary)) return;
    setIsSaving(true);
    try {
      const { nodes, edges } = useBuilderStore.getState();
      const version = await api.createVersion(
        documentId,
        { canvas_json: { nodes, edges } },
        workspaceId
      );
      await api.promoteVersion(
        documentId,
        version.id,
        { version_name: summary.trim(), version_description: body.trim() || undefined },
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
  }, [summary, body, documentId, workspaceId, onCommitted, onOpenChange, t]);

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
                  {categoryLabel(c.category)}
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

          <Button variant="ghost" size="sm" disabled title={t("versionExplainSoon")}>
            <Sparkles className="size-3.5 mr-1" />
            {t("versionExplainDiff")}
          </Button>
        </div>

        <div className="flex justify-end gap-2 pt-1">
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            {t("versionCancel")}
          </Button>
          <Button
            size="sm"
            onClick={handleCommit}
            disabled={!isValidSummary(summary) || isSaving}
          >
            {isSaving ? t("versionCommitting") : t("versionCommit")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
