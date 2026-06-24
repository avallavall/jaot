
// Canvas Serializer — Converts React Flow canvas state to
// OptimizationProblem JSON accepted by POST /api/v2/solve

import type { Node, Edge } from "@xyflow/react";
import type { OptimizationProblem, Variable, Constraint, Objective } from "@/lib/types";
import type {
  VariableNodeData,
  ConstraintNodeData,
  ObjectiveNodeData,
  CoefficientEdgeData,
} from "@/lib/builder/types";

function buildExpression(
  varNodes: Node<VariableNodeData>[],
  incomingEdges: Edge<CoefficientEdgeData>[]
): string {
  const terms: string[] = [];

  for (const edge of incomingEdges) {
    const sourceNode = varNodes.find((n) => n.id === edge.source);
    if (!sourceNode) continue;

    const coeff = edge.data?.coefficient ?? 1;
    if (coeff === 0) continue; // Skip zero-coefficient terms

    const varName = sourceNode.data.name;

    if (terms.length === 0) {
      // First term
      if (coeff === 1) {
        terms.push(varName);
      } else if (coeff === -1) {
        terms.push(`-${varName}`);
      } else {
        terms.push(`${coeff}*${varName}`);
      }
    } else {
      // Subsequent terms — handle sign explicitly
      if (coeff > 0) {
        if (coeff === 1) {
          terms.push(`+ ${varName}`);
        } else {
          terms.push(`+ ${coeff}*${varName}`);
        }
      } else {
        const absCoeff = Math.abs(coeff);
        if (absCoeff === 1) {
          terms.push(`- ${varName}`);
        } else {
          terms.push(`- ${absCoeff}*${varName}`);
        }
      }
    }
  }

  return terms.length > 0 ? terms.join(" ") : "0";
}

// Main export

/**
 * Serialize a React Flow canvas (nodes + edges) into an OptimizationProblem
 * that can be sent to POST /api/v2/solve.
 */
export function serializeToOptimizationProblem(
  nodes: Node[],
  edges: Edge[]
): OptimizationProblem {
  // Separate nodes by type
  const varNodes = nodes.filter((n) => n.type === "variable") as Node<VariableNodeData>[];
  const constraintNodes = nodes.filter((n) => n.type === "constraint") as Node<ConstraintNodeData>[];
  const objectiveNode = nodes.find((n) => n.type === "objective") as
    | Node<ObjectiveNodeData>
    | undefined;

  const typedEdges = edges as Edge<CoefficientEdgeData>[];

  // Build variables list
  const variables: Variable[] = varNodes.map((node) => {
    const v: Variable = {
      name: node.data.name,
      type: node.data.type,
    };
    if (node.data.lower_bound !== null && node.data.lower_bound !== undefined) {
      v.lower_bound = node.data.lower_bound;
    }
    if (node.data.upper_bound !== null && node.data.upper_bound !== undefined) {
      v.upper_bound = node.data.upper_bound;
    }
    return v;
  });

  // Build objective
  const objEdges = objectiveNode
    ? typedEdges.filter((e) => e.target === objectiveNode.id)
    : [];
  const objExpression = buildExpression(varNodes, objEdges);

  const objective: Objective = {
    sense: (objectiveNode?.data?.sense ?? "minimize") as "minimize" | "maximize",
    expression: objExpression,
  };

  // Build constraints
  const constraints: Constraint[] = constraintNodes.map((node) => {
    const incomingEdges = typedEdges.filter((e) => e.target === node.id);
    const lhs = buildExpression(varNodes, incomingEdges);
    const operator = node.data.operator;
    const rhs = node.data.rhs;

    return {
      name: node.data.name,
      expression: `${lhs} ${operator} ${rhs}`,
    };
  });

  return {
    variables,
    objective,
    constraints,
  };
}
