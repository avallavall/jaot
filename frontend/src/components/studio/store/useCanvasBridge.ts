"use client";

import { useEffect, useRef } from "react";
import {
  useBuilderStore,
  pauseTracking,
  resumeTracking,
} from "@/hooks/useBuilderStore";
import { canvasProjector } from "./projectors";
import type { ModelProjectStore } from "./createModelProjectStore";

const DEBOUNCE_MS = 300;

/**
 * Keeps the canvas working-state (the global builder store) and the canonical
 * model store in sync, loop-safely.
 *
 * Two independent guards prevent a canvas -> canonical -> canvas ping-pong:
 *  1. `isProjecting` — while we push the canonical model INTO the canvas, canvas
 *     change events are ignored, so a programmatic projection cannot echo back.
 *  2. `setProblem` is idempotent — re-serializing the canvas yields the model that
 *     is already canonical, so even an unguarded event settles to a no-op.
 *
 * In 2A only the canvas authors edits, so the canonical -> canvas direction is
 * dormant (it fires only for non-canvas sources like the future Editor/Assistant).
 */
export function useCanvasBridge(store: ModelProjectStore): void {
  const isProjecting = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // Canvas -> canonical (debounced).
    const unsubCanvas = useBuilderStore.subscribe((state, prev) => {
      if (isProjecting.current) return;
      // Hairball guard: a too-large model has an intentionally empty canvas — its
      // truth lives in model_json, so an empty-canvas projection must never
      // overwrite (and re-deriving the canvas would freeze the tab anyway).
      if (store.getState().canvasDisabled) return;
      if (state.nodes === prev.nodes && state.edges === prev.edges) return;
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        // Re-check at fire time: the canvas may have been disabled (large model)
        // between scheduling and firing — projecting an empty canvas now would
        // clobber the canonical model and autosave the emptiness.
        if (store.getState().canvasDisabled) return;
        const { nodes, edges } = useBuilderStore.getState();
        const projected = canvasProjector.toProblem({ nodes, edges });
        // Guard against a spurious empty-canvas projection clobbering a non-empty
        // model. When the model was authored elsewhere (DSL / Editor / AI) the canvas
        // is only a projection; a canvas that is empty (or was never laid out — e.g.
        // the DSL lens keeps the canvas unmounted) must NOT flow an empty model back
        // over the real one. Silently emptying the model is data loss; a genuine
        // "clear the canvas" is recoverable via undo.
        const projectedEmpty =
          projected.variables.length === 0 && projected.constraints.length === 0;
        const current = store.getState().problem;
        const currentNonEmpty =
          current.variables.length > 0 || current.constraints.length > 0;
        if (projectedEmpty && currentNonEmpty) return;
        store.getState().setProblem(projected, { source: "canvas" });
      }, DEBOUNCE_MS);
    });

    // Canonical -> canvas (only for non-canvas sources).
    const unsubModel = store.subscribe((state, prev) => {
      if (state.problem === prev.problem) return;
      if (state.canvasDisabled) return;
      if (state.lastSource === "canvas" || state.lastSource === null) return;
      isProjecting.current = true;
      try {
        const { nodes, edges } = canvasProjector.fromProblem(state.problem);
        pauseTracking();
        const docId = useBuilderStore.getState().documentId ?? state.modelId;
        useBuilderStore.getState().setDocument(docId, state.name, nodes, edges);
      } finally {
        resumeTracking();
        isProjecting.current = false;
      }
    });

    return () => {
      if (timer.current) clearTimeout(timer.current);
      unsubCanvas();
      unsubModel();
    };
  }, [store]);
}
