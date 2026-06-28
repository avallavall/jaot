"use client";

import { useEffect, useRef } from "react";
import { useBuilderStore } from "@/hooks/useBuilderStore";
import { api } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import type { ModelProjectStore } from "./createModelProjectStore";
import type { OptimizationProblem } from "@/lib/types";

const DEBOUNCE_MS = 800;

/**
 * Persists the canonical model to the draft (the builder document, day-1) whenever
 * it changes from a real edit. Idempotent no-ops (e.g. the load-time projection)
 * never set `headDirty`, so they do not trigger a save. The real `ModelProject`
 * draft endpoint replaces the builder-document PUT in P1.
 */
export function useAutosave(store: ModelProjectStore, modelId: string): void {
  const { activeWorkspaceId } = useAuth();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!modelId || modelId === "new") return;

    const persist = (problem: OptimizationProblem) => {
      store.getState().setSaveState("saving");
      const { nodes, edges } = useBuilderStore.getState();
      api
        .updateBuilderDocument(
          modelId,
          {
            model_json: problem as unknown as Record<string, unknown>,
            canvas_json: { nodes, edges } as unknown as Record<string, unknown>,
          },
          activeWorkspaceId ?? undefined
        )
        .then(() => store.getState().setSaveState("saved"))
        .catch(() => store.getState().setSaveState("error"));
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
