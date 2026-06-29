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
        const { nodes, edges } = useBuilderStore.getState();
        const problem = canvasProjector.toProblem({ nodes, edges });
        store.getState().setProblem(problem, { source: "canvas" });
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
