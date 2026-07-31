import { deserializeFromOptimizationProblem } from "@/lib/builder/deserializer";
import { serializeToOptimizationProblem } from "@/lib/builder/serializer";
import {
  constraintExpressionsEquivalent,
  linearExpressionsEquivalent,
} from "@/lib/builder/linear";
import type { BuilderNode, BuilderEdge } from "@/lib/builder/types";
import type { OptimizationProblem } from "@/lib/types";
import { canvasCanRepresentModel, exceedsCanvasScale } from "./model-scale";

export interface DraftCanvas {
  nodes: BuilderNode[];
  edges: BuilderEdge[];
}

/**
 * Whether a canvas, serialized back, denotes the SAME model as `modelJson` —
 * variables with identical type/bounds, an equivalent linear objective, and
 * positionally equivalent linear constraints (term order and constant placement
 * ignored; a constraint name only has to match when the model actually has one).
 *
 * This is the trust test for a STORED canvas: a stale or degenerate canvas
 * (e.g. one saved by the old lossy deserializer — 51 nodes, 4 edges, `0 <= 0`
 * defaults) serializes to a different model and must be discarded, never used
 * as the source the canonical model is hydrated from.
 */
export function canvasRepresentsModel(
  canvas: DraftCanvas,
  modelJson: OptimizationProblem
): boolean {
  const serialized = serializeToOptimizationProblem(canvas.nodes, canvas.edges);

  if (serialized.variables.length !== (modelJson.variables?.length ?? 0)) return false;
  const byName = new Map(serialized.variables.map((v) => [v.name, v]));
  for (const variable of modelJson.variables) {
    const twin = byName.get(variable.name);
    if (
      !twin ||
      twin.type !== variable.type ||
      (twin.lower_bound ?? null) !== (variable.lower_bound ?? null) ||
      (twin.upper_bound ?? null) !== (variable.upper_bound ?? null)
    ) {
      return false;
    }
  }

  if (serialized.objective.sense !== modelJson.objective.sense) return false;
  if (
    !linearExpressionsEquivalent(
      serialized.objective.expression,
      modelJson.objective.expression
    )
  ) {
    return false;
  }

  const modelConstraints = modelJson.constraints ?? [];
  if (serialized.constraints.length !== modelConstraints.length) return false;
  for (let i = 0; i < modelConstraints.length; i++) {
    const model = modelConstraints[i];
    const twin = serialized.constraints[i];
    if (model.name != null && twin.name !== model.name) return false;
    if (!constraintExpressionsEquivalent(twin.expression, model.expression)) return false;
  }
  return true;
}

/**
 * Resolve the canvas to render for a ModelProject draft.
 *
 * Precedence:
 *  1. the stored `draft_canvas_json` — IF, serialized back, it denotes the model
 *     ({@link canvasRepresentsModel}); a stale or degenerate stored canvas (fewer
 *     nodes than variables, missing coefficient edges, defaulted `0 <= 0` rows)
 *     is discarded, never trusted;
 *  2. otherwise derive the canvas from the canonical `draft_model_json` — e.g. an
 *     API/ERP consumer created the project with only `model_json` and no canvas,
 *     OR the stored canvas failed the trust test — and only keep a derivation the
 *     deserializer certifies as faithful;
 *  3. otherwise empty (the caller must then work from the model directly).
 *
 * A model too large for the canvas ({@link exceedsCanvasScale}) or not exactly
 * representable on it ({@link canvasCanRepresentModel}) is NEVER deserialized
 * here — the caller detects the same conditions and works from the model
 * directly, with the canvas lens withheld.
 */
export function resolveDraftCanvas(
  canvasJson: { nodes?: unknown[]; edges?: unknown[] } | null | undefined,
  modelJson: OptimizationProblem | null | undefined
): DraftCanvas {
  const nodes = Array.isArray(canvasJson?.nodes) ? (canvasJson!.nodes as BuilderNode[]) : [];
  const edges = Array.isArray(canvasJson?.edges) ? (canvasJson!.edges as BuilderEdge[]) : [];

  const hasModel =
    modelJson != null && Array.isArray(modelJson.variables) && modelJson.variables.length > 0;

  if (nodes.length > 0) {
    // No model to check against → the canvas IS the document (legacy/new flows).
    if (!hasModel) return { nodes, edges };
    if (canvasRepresentsModel({ nodes, edges }, modelJson!)) return { nodes, edges };
  }
  if (hasModel && !exceedsCanvasScale(modelJson) && canvasCanRepresentModel(modelJson)) {
    const derived = deserializeFromOptimizationProblem(modelJson!);
    if (derived.faithful) return { nodes: derived.nodes, edges: derived.edges };
  }
  return { nodes: [], edges: [] };
}
