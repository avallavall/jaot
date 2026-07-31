// Converts OptimizationProblem JSON back into React Flow canvas nodes and edges.
import type { Node } from "@xyflow/react";
import type { OptimizationProblem } from "@/lib/types";
import type {
  VariableNodeData,
  ConstraintNodeData,
  ObjectiveNodeData,
  CoefficientEdgeData,
  BuilderNode,
  BuilderEdge,
} from "@/lib/builder/types";
import { applyDagreLayout } from "@/lib/builder/autoLayout";
import { parseLinearSide, parseLinearConstraint, type LinearTerm } from "@/lib/builder/linear";

export interface DeserializedCanvas {
  nodes: BuilderNode[];
  edges: BuilderEdge[];
  /**
   * False when some expression could NOT be represented exactly as edges + RHS —
   * a constraint with unparseable structure, an objective constant, a term over
   * an undeclared variable. An unfaithful canvas is a partial VIEW: serializing
   * it back would produce a DIFFERENT model, so it must never become the source
   * of truth (see the studio provider's fidelity gate).
   */
  faithful: boolean;
}

let deserializeCounter = 0;
function nextId(): string {
  return String(++deserializeCounter);
}

/** Returns canvas nodes/edges with auto-layout applied, plus a fidelity verdict. */
export function deserializeFromOptimizationProblem(
  problem: OptimizationProblem
): DeserializedCanvas {
  const nodes: BuilderNode[] = [];
  const edges: BuilderEdge[] = [];
  let faithful = true;

  const varNodeIds = new Map<string, string>();

  for (const variable of problem.variables) {
    const nodeId = `var-${variable.name}`;
    varNodeIds.set(variable.name, nodeId);

    const varNode: Node<VariableNodeData, "variable"> = {
      id: nodeId,
      type: "variable",
      position: { x: 0, y: 0 }, // set by auto-layout below
      data: {
        name: variable.name,
        type: variable.type as "continuous" | "integer" | "binary",
        lower_bound: variable.lower_bound ?? null,
        upper_bound: variable.upper_bound ?? null,
      },
    };
    nodes.push(varNode);
  }

  /** Emit one coefficient edge per combined term; report whether all terms landed. */
  const addEdges = (terms: LinearTerm[], targetId: string, tag: string): boolean => {
    let complete = true;
    for (const term of terms) {
      const sourceId = varNodeIds.get(term.varName);
      if (!sourceId) {
        complete = false; // a term over an undeclared variable cannot be an edge
        continue;
      }
      edges.push({
        id: `edge-${tag}-${term.varName}-${nextId()}`,
        source: sourceId,
        target: targetId,
        type: "coefficient",
        data: { coefficient: term.coefficient } as CoefficientEdgeData,
      });
    }
    return complete;
  };

  const objectiveNodeId = "objective-1";
  const objNode: Node<ObjectiveNodeData, "objective"> = {
    id: objectiveNodeId,
    type: "objective",
    position: { x: 0, y: 0 },
    deletable: false,
    data: {
      sense: problem.objective.sense as "minimize" | "maximize",
      formula: "",
    },
  };
  nodes.push(objNode);

  const objSide = parseLinearSide(problem.objective.expression);
  if (objSide === null || Math.abs(objSide.constant) > 0) {
    // Not linear-readable, or carries a constant no edge can represent.
    faithful = false;
  }
  if (objSide !== null) {
    faithful = addEdges(objSide.terms, objectiveNodeId, "obj") && faithful;
  }

  for (let i = 0; i < problem.constraints.length; i++) {
    const constraint = problem.constraints[i];
    const constraintNodeId = `constraint-${i}`;

    // The general linear read: variables on BOTH sides, constants anywhere,
    // normalized to `terms OP rhs`. `null` means the canvas cannot hold this
    // constraint — the node below is then only a display stub, and the whole
    // canvas is flagged unfaithful instead of silently pretending "0 <= 0".
    const parsed = parseLinearConstraint(constraint.expression);
    if (parsed === null) faithful = false;

    const constraintNode: Node<ConstraintNodeData, "constraint"> = {
      id: constraintNodeId,
      type: "constraint",
      position: { x: 0, y: 0 },
      data: {
        name: constraint.name ?? `c${i + 1}`,
        operator: parsed?.operator ?? "<=",
        rhs: parsed?.rhs ?? 0,
        formula: constraint.expression, // raw expression as fallback display
      },
    };
    nodes.push(constraintNode);

    if (parsed) {
      faithful = addEdges(parsed.terms, constraintNodeId, `c${i}`) && faithful;
    }
  }

  const { nodes: layoutedNodes, edges: layoutedEdges } = applyDagreLayout(nodes, edges);

  return {
    nodes: layoutedNodes as BuilderNode[],
    edges: layoutedEdges as BuilderEdge[],
    faithful,
  };
}
