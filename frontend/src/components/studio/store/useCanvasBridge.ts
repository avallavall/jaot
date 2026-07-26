"use client";

import { useEffect, useRef } from "react";
import {
  useBuilderStore,
  pauseTracking,
  resumeTracking,
} from "@/hooks/useBuilderStore";
import type { OptimizationProblem } from "@/lib/types";
import { canvasProjector } from "./projectors";
import type { ModelProjectStore } from "./createModelProjectStore";

const DEBOUNCE_MS = 300;

type Variable = OptimizationProblem["variables"][number];
type Constraint = OptimizationProblem["constraints"][number];

/**
 * Re-attach the server-derived index structure (`family`/`index_tuple`, A1) the canvas
 * cannot represent onto freshly projected variables, matched by name. The canvas nodes
 * carry only name/type/bounds, so without this a reprojection of an untouched canvas
 * would drop those fields and no longer be JSON-equal to the canonical model — the
 * equality guard (`problemsEqual`) would then fire a phantom `setProblem(source:"canvas")`
 * and drift the DSL/editor source to read-only just from VIEWING the canvas. A genuinely
 * new canvas variable (no prior of that name) keeps no structure, which is correct.
 */
export function reattachVariableStructure(
  projected: readonly Variable[],
  current: readonly Variable[]
): Variable[] {
  const priorByName = new Map(current.map((v) => [v.name, v]));
  return projected.map((v) => {
    const prior = priorByName.get(v.name);
    return prior ? { ...v, family: prior.family, index_tuple: prior.index_tuple } : v;
  });
}

/**
 * The same re-attachment for constraint rows. Sensitivity L1 gave `Constraint` its own
 * server-stamped `family` (same contract as `Variable.family`) and the canvas has no node
 * field for it, so a reprojection dropped it — and since `problemsEqual` is a full JSON
 * compare, a canonical `"family": null` versus an ABSENT key counted as a change. Merely
 * opening the canvas sub-lens therefore fired the phantom `setProblem(source:"canvas")`
 * this module's variable path already guards against: the JModel lens locked read-only
 * behind "The model was changed elsewhere" (which was false), its dataset selector went
 * dead, and the studio autosaved a draft nobody edited.
 *
 * Matched by name, so an unnamed or genuinely new constraint keeps no family — correct,
 * since family membership is re-derived by the next compile.
 */
export function reattachConstraintStructure(
  projected: readonly Constraint[],
  current: readonly Constraint[]
): Constraint[] {
  const priorByName = new Map(
    current.filter((c) => c.name != null).map((c) => [c.name, c] as const)
  );
  return projected.map((c) => {
    const prior = c.name != null ? priorByName.get(c.name) : undefined;
    return prior ? { ...c, family: prior.family } : c;
  });
}

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
        // The canvas is a PARTIAL lens: it authors variables/objective/constraints but
        // not name/options/warm_start/metadata. Merge over the canonical problem so an
        // untouched canvas reprojects to an IDENTICAL model (setProblem's equality
        // guard no-ops → no phantom edit/autosave, no false "changed elsewhere" drift
        // for the JModel/editor lenses) and a real canvas edit never silently drops
        // the fields the canvas cannot represent.
        //
        // Per row, re-attach the server-derived structure the canvas cannot represent
        // (see reattachVariableStructure / reattachConstraintStructure) so an untouched
        // canvas stays JSON-identical and never drifts the DSL/editor source read-only
        // on a mere view.
        store.getState().setProblem(
          {
            ...current,
            variables: reattachVariableStructure(projected.variables, current.variables),
            objective: projected.objective,
            constraints: reattachConstraintStructure(projected.constraints, current.constraints),
          },
          { source: "canvas" }
        );
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
