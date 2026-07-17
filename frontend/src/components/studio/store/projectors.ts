import type { Node, Edge } from "@xyflow/react";
import type { OptimizationProblem } from "@/lib/types";
import type { BuilderNode, BuilderEdge } from "@/lib/builder/types";
import { serializeToOptimizationProblem } from "@/lib/builder/serializer";
import { deserializeFromOptimizationProblem } from "@/lib/builder/deserializer";
import type { RepKey } from "./createModelProjectStore";

export interface CanvasView {
  nodes: BuilderNode[];
  edges: BuilderEdge[];
}

/**
 * A projector translates between the canonical `OptimizationProblem` and one
 * representation. `toProblem` runs on edit; `fromProblem` rebuilds the view when
 * the canonical model changed elsewhere.
 */
export interface Projector<View> {
  toProblem: (view: View) => OptimizationProblem;
  fromProblem: (problem: OptimizationProblem) => View;
}

export const canvasProjector: Projector<CanvasView> = {
  toProblem: ({ nodes, edges }) =>
    serializeToOptimizationProblem(nodes as Node[], edges as Edge[]),
  fromProblem: (problem) => deserializeFromOptimizationProblem(problem),
};

function notImplemented(rep: RepKey): never {
  throw new Error(`Projector for "${rep}" is not implemented yet`);
}

/**
 * The Editor (text) lens serializes the canonical model to pretty-printed JSON.
 * The reverse direction (text -> problem) is deliberately NOT this projector's job:
 * the editor needs a typed parse Result (syntax + shape errors for inline feedback)
 * that the throwing `Projector.toProblem` signature can't carry, so it lives in
 * `panels/editor/parse.ts` (`parseModelText`). Leaving `toProblem` unimplemented
 * keeps a single, shape-checking parser instead of a second weaker `JSON.parse`.
 */
export const scratchProjector: Projector<string> = {
  toProblem: () => notImplemented("scratch"),
  fromProblem: (problem) => JSON.stringify(problem, null, 2),
};

// Registered for shape-completeness; wired when the Assistant (formulation) lens
// lands. Never invoked yet.
export const formulationProjector: Projector<unknown> = {
  toProblem: () => notImplemented("formulation"),
  fromProblem: () => notImplemented("formulation"),
};
