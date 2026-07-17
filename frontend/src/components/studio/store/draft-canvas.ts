import { deserializeFromOptimizationProblem } from "@/lib/builder/deserializer";
import type { BuilderNode, BuilderEdge } from "@/lib/builder/types";
import type { OptimizationProblem } from "@/lib/types";
import { exceedsCanvasScale } from "./model-scale";

export interface DraftCanvas {
  nodes: BuilderNode[];
  edges: BuilderEdge[];
}

/**
 * Resolve the canvas to render for a ModelProject draft.
 *
 * Precedence:
 *  1. the stored `draft_canvas_json` — IF it plausibly represents the model (see
 *     the staleness guard below);
 *  2. otherwise derive the canvas from the canonical `draft_model_json` — e.g. an
 *     API/ERP consumer created the project with only `model_json` and no canvas, OR
 *     a stored canvas went stale relative to model_json;
 *  3. otherwise empty.
 *
 * Staleness guard: the builder lays out at least one node per variable, so a stored
 * canvas with FEWER nodes than the model has variables cannot represent it — it is a
 * stale/degenerate canvas left when a non-canvas source (AI Assistant / Editor)
 * replaced the model while the canvas was disabled. Trusting it would render the
 * workspace EMPTY next to a real model_json. In that case we derive from the model so
 * the real model shows (and the next save rewrites a matching canvas).
 *
 * A model too large for the canvas ({@link exceedsCanvasScale}) is NEVER
 * deserialized here — laying out tens of thousands of nodes would freeze the
 * tab. The caller detects the same condition and works from the model directly.
 */
export function resolveDraftCanvas(
  canvasJson: { nodes?: unknown[]; edges?: unknown[] } | null | undefined,
  modelJson: OptimizationProblem | null | undefined
): DraftCanvas {
  const nodes = Array.isArray(canvasJson?.nodes) ? (canvasJson!.nodes as BuilderNode[]) : [];
  const edges = Array.isArray(canvasJson?.edges) ? (canvasJson!.edges as BuilderEdge[]) : [];
  const modelVarCount =
    modelJson && Array.isArray(modelJson.variables) ? modelJson.variables.length : 0;

  // Trust the stored canvas only if it is at least as large as the model's variable
  // count (one node per variable, plus constraint/objective nodes) — otherwise it is
  // stale and would render empty over a real model.
  if (nodes.length > 0 && nodes.length >= modelVarCount) {
    return { nodes, edges };
  }
  if (
    modelJson &&
    Array.isArray(modelJson.variables) &&
    modelJson.variables.length > 0 &&
    !exceedsCanvasScale(modelJson)
  ) {
    return deserializeFromOptimizationProblem(modelJson);
  }
  return { nodes: [], edges: [] };
}
