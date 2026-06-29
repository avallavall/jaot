"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/AuthContext";
import { api } from "@/lib/api";
import { useBuilderStore } from "@/hooks/useBuilderStore";
import { serializeToOptimizationProblem } from "@/lib/builder/serializer";
import type { BuilderNode, BuilderEdge } from "@/lib/builder/types";
import type { ModelVersionListItem } from "@/lib/types";
import {
  useModelProjectStore,
  useModelProjectStoreApi,
} from "../store/useModelProjectStore";
import { CommitDialog } from "./CommitDialog";
import { VersionSelector } from "./VersionSelector";
import { VersionHistoryDrawer } from "./VersionHistoryDrawer";
import { uncommittedSince } from "./commit-helpers";

/**
 * All version control for the workspace header: the "vK" selector + recent dropdown,
 * the ambient "uncommitted changes since vK" line, the Commit button (+ dialog),
 * the full history drawer, restore, and the Cmd/Ctrl+S shortcut.
 *
 * Concept: autosave writes silent checkpoints (the draft); a *version* is an explicit,
 * message-required milestone. Committing requires a non-empty "What changed?".
 */
export function VersionControls() {
  const t = useTranslations("studio");
  const { activeWorkspaceId } = useAuth();
  const modelId = useModelProjectStore((s) => s.modelId);
  const headDirty = useModelProjectStore((s) => s.headDirty);
  const storeApi = useModelProjectStoreApi();

  const [commitOpen, setCommitOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [counter, setCounter] = useState(0);
  const [latest, setLatest] = useState<ModelVersionListItem | null>(null);

  const isPersisted = !!modelId && modelId !== "new";

  // Latest committed version (for the badge + ambient line); refetched on commit/restore.
  useEffect(() => {
    if (!isPersisted) return;
    let cancelled = false;
    api
      .listVersions(modelId, { limit: 1 }, activeWorkspaceId ?? undefined)
      .then((list) => {
        if (!cancelled) setLatest(list[0] ?? null);
      })
      .catch(() => {
        /* versions are non-critical */
      });
    return () => {
      cancelled = true;
    };
  }, [modelId, activeWorkspaceId, counter, isPersisted]);

  // Cmd/Ctrl+S opens the commit dialog — but not while typing in a field or the editor.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== "s") return;
      const el = document.activeElement as HTMLElement | null;
      const tag = el?.tagName.toLowerCase();
      if (tag === "input" || tag === "textarea" || el?.isContentEditable) return;
      e.preventDefault();
      if (isPersisted) setCommitOpen(true);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isPersisted]);

  const handleCommitted = useCallback(() => {
    storeApi.getState().markCommitted();
    setCounter((c) => c + 1);
  }, [storeApi]);

  const handleRestore = useCallback(
    async (versionId: string) => {
      try {
        const { nodes, edges } = useBuilderStore.getState();
        const { document: restored } = await api.restoreVersion(
          modelId,
          versionId,
          { current_canvas_json: { nodes, edges } },
          activeWorkspaceId ?? undefined
        );
        const canvas = restored.canvas_json as { nodes?: unknown[]; edges?: unknown[] } | null;
        const newNodes = Array.isArray(canvas?.nodes) ? (canvas!.nodes as BuilderNode[]) : [];
        const newEdges = Array.isArray(canvas?.edges) ? (canvas!.edges as BuilderEdge[]) : [];
        useBuilderStore.getState().setDocument(restored.id, restored.name, newNodes, newEdges);
        storeApi
          .getState()
          .hydrate(serializeToOptimizationProblem(newNodes, newEdges), restored.name);
        setCounter((c) => c + 1);
        setHistoryOpen(false);
        toast.success(t("versionRestored"));
      } catch {
        toast.error(t("versionRestoreFailed"));
      }
    },
    [modelId, activeWorkspaceId, storeApi, t]
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
        documentId={modelId}
        latestSequence={latest?.sequence ?? null}
        saveCounter={counter}
        onViewAll={() => setHistoryOpen(true)}
        onRestore={handleRestore}
      />

      <Button variant="outline" size="sm" onClick={() => setCommitOpen(true)}>
        <Save className="h-4 w-4 mr-1" />
        {t("headerCommit")}
      </Button>

      <CommitDialog
        open={commitOpen}
        onOpenChange={setCommitOpen}
        documentId={modelId}
        workspaceId={activeWorkspaceId ?? undefined}
        onCommitted={handleCommitted}
      />
      <VersionHistoryDrawer
        documentId={modelId}
        isOpen={historyOpen}
        onClose={() => setHistoryOpen(false)}
        onRestore={handleRestore}
      />
    </div>
  );
}
