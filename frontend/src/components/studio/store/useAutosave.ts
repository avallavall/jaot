"use client";

import { useEffect, useRef } from "react";
import { useBuilderStore } from "@/hooks/useBuilderStore";
import { api } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import type { ModelProjectStore } from "./createModelProjectStore";
import type { OptimizationProblem } from "@/lib/types";

const DEBOUNCE_MS = 800;

/**
 * Persists the canonical model to the `ModelProject` HEAD draft (`PUT
 * /projects/{id}/draft`) whenever it changes from a real edit. Idempotent no-ops
 * (e.g. the load-time projection) never set `headDirty`, so they do not trigger a
 * save. Optimistic concurrency via the `draft_lock_version` (`If-Match`): on a 409
 * (another writer advanced the draft) we refetch the lock and retry once with the
 * user's in-memory model, so an edit is never silently lost.
 */
export function useAutosave(store: ModelProjectStore, modelId: string): void {
  const { activeWorkspaceId } = useAuth();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!modelId || modelId === "new") return;
    const ws = activeWorkspaceId ?? undefined;

    const persist = (problem: OptimizationProblem) => {
      const { nodes, edges } = useBuilderStore.getState();
      const body = {
        model_json: problem as unknown as Record<string, unknown>,
        canvas_json: { nodes, edges } as unknown as Record<string, unknown>,
      };
      store.getState().setSaveState("saving");
      api
        .updateProjectDraft(modelId, body, store.getState().lockVersion, ws)
        .then((project) => {
          store.getState().setLockVersion(project.draft_lock_version);
          store.getState().setSaveState("saved");
        })
        .catch(async (err: unknown) => {
          if ((err as { status?: number })?.status === 409) {
            try {
              const latest = await api.getProject(modelId, ws);
              const retry = await api.updateProjectDraft(
                modelId,
                body,
                latest.draft_lock_version,
                ws
              );
              store.getState().setLockVersion(retry.draft_lock_version);
              store.getState().setSaveState("saved");
              return;
            } catch {
              /* fall through to the error state below */
            }
          }
          store.getState().setSaveState("error");
        });
    };

    const unsub = store.subscribe((state, prev) => {
      if (state.problem === prev.problem) return;
      if (!state.headDirty) return;
      if (timer.current) clearTimeout(timer.current);
      const problem = state.problem;
      timer.current = setTimeout(() => persist(problem), DEBOUNCE_MS);
    });

    return () => {
      if (timer.current) clearTimeout(timer.current);
      unsub();
    };
  }, [store, modelId, activeWorkspaceId]);
}
