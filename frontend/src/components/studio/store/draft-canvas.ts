import { deserializeFromOptimizationProblem } from "@/lib/builder/deserializer";
import type { BuilderNode, BuilderEdge } from "@/lib/builder/types";
import type { OptimizationProblem } from "@/lib/types";

export interface DraftCanvas {
  nodes: BuilderNode[];
  edges: BuilderEdge[];
}

/**
 * Resolve the canvas to render for a ModelProject draft.
 *
 * Precedence:
 *  1. the stored `draft_canvas_json` — the model was authored in the UI;
 *  2. otherwise derive the canvas from the canonical `draft_model_json` — e.g. an
 *     API/ERP consumer created the project with only `model_json` and no canvas;
 *     without this the workspace would render empty for them;
 *  3. otherwise empty.
 */
export function resolveDraftCanvas(
  canvasJson: { nodes?: unknown[]; edges?: unknown[] } | null | undefined,
  modelJson: OptimizationProblem | null | undefined
): DraftCanvas {
  const nodes = Array.isArray(canvasJson?.nodes) ? (canvasJson!.nodes as BuilderNode[]) : [];
  const edges = Array.isArray(canvasJson?.edges) ? (canvasJson!.edges as BuilderEdge[]) : [];
  if (nodes.length > 0) {
    return { nodes, edges };
  }
  if (modelJson && Array.isArray(modelJson.variables) && modelJson.variables.length > 0) {
    return deserializeFromOptimizationProblem(modelJson);
  }
  return { nodes: [], edges: [] };
}
