"use client";

import { useEffect, useRef } from "react";
import { useBuilderStore } from "@/hooks/useBuilderStore";
import { api } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import type { ModelProjectStore } from "./createModelProjectStore";

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

    const persist = () => {
      const st = store.getState();
      const { nodes, edges } = useBuilderStore.getState();
      const body = {
        model_json: st.problem as unknown as Record<string, unknown>,
        canvas_json: { nodes, edges } as unknown as Record<string, unknown>,
        // Persist the JModel source once the user has touched it this session (`dslDirty`),
        // sending it even when empty so a deletion sticks. Before the user edits the DSL,
        // it is omitted so a canvas/JSON edit never wipes a not-yet-hydrated source.
        ...(st.dslDirty ? { dsl_source: st.draftDslSource } : {}),
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
      // Save on a real model change OR a JModel-source edit (which may not change the
      // compiled model — e.g. broken text — but must still be persisted so it survives
      // navigation). Load-time projections never set headDirty, so they don't save.
      if (state.problem === prev.problem && state.draftDslSource === prev.draftDslSource) return;
      if (!state.headDirty) return;
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => persist(), DEBOUNCE_MS);
    });

    return () => {
      if (timer.current) clearTimeout(timer.current);
      unsub();
    };
  }, [store, modelId, activeWorkspaceId]);
}
