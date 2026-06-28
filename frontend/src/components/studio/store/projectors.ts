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

// Registered for shape-completeness; wired when the Editor (scratch) and the
// Assistant (formulation) lenses land. They are never invoked in 2A.
export const scratchProjector: Projector<string> = {
  toProblem: () => notImplemented("scratch"),
  fromProblem: () => notImplemented("scratch"),
};

export const formulationProjector: Projector<unknown> = {
  toProblem: () => notImplemented("formulation"),
  fromProblem: () => notImplemented("formulation"),
};
