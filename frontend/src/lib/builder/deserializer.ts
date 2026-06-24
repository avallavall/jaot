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

interface ParsedTerm {
  coefficient: number;
  varName: string;
}

interface ParsedConstraint {
  terms: ParsedTerm[];
  operator: "<=" | ">=" | "==";
  rhs: number;
}

/** Parse a linear expression like "2*x + 3*y" into coefficient-tagged terms. */
function parseExpression(expr: string): ParsedTerm[] {
  const terms: ParsedTerm[] = [];

  const normalized = expr.trim().replace(/\s*([+-])\s*/g, " $1 ").trim();

  // [sign] [coefficient] [*] varName — e.g. "2*x", "-3.5*y", "x", "-y", "+ 2*z".
  const termRegex = /([+-]?\s*\d*\.?\d*)\s*\*?\s*([a-zA-Z_]\w*)/g;
  let match: RegExpExecArray | null;

  while ((match = termRegex.exec(normalized)) !== null) {
    const coeffStr = match[1].replace(/\s/g, "");
    const varName = match[2];

    let coefficient: number;
    if (coeffStr === "" || coeffStr === "+") {
      coefficient = 1;
    } else if (coeffStr === "-") {
      coefficient = -1;
    } else {
      const parsed = parseFloat(coeffStr);
      coefficient = isNaN(parsed) ? 1 : parsed;
    }

    terms.push({ coefficient, varName });
  }

  return terms;
}

/** Parse a constraint like "2*x + 3*y <= 10" into terms, operator, RHS. */
function parseConstraintExpression(expr: string): ParsedConstraint | null {
  let operator: "<=" | ">=" | "==" = "<=";
  let splitIdx = -1;

  if (expr.includes("<=")) {
    operator = "<=";
    splitIdx = expr.indexOf("<=");
  } else if (expr.includes(">=")) {
    operator = ">=";
    splitIdx = expr.indexOf(">=");
  } else if (expr.includes("==")) {
    operator = "==";
    splitIdx = expr.indexOf("==");
  } else {
    return null;
  }

  const lhsStr = expr.substring(0, splitIdx).trim();
  const rhsStr = expr.substring(splitIdx + 2).trim();
  const rhs = parseFloat(rhsStr);

  if (isNaN(rhs)) return null;

  const terms = parseExpression(lhsStr);
  return { terms, operator, rhs };
}

let deserializeCounter = 0;
function nextId(): string {
  return String(++deserializeCounter);
}

/** Returns canvas nodes/edges with auto-layout applied. */
export function deserializeFromOptimizationProblem(problem: OptimizationProblem): {
  nodes: BuilderNode[];
  edges: BuilderEdge[];
} {
  const nodes: BuilderNode[] = [];
  const edges: BuilderEdge[] = [];

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

  try {
    const objTerms = parseExpression(problem.objective.expression);
    for (const term of objTerms) {
      const sourceId = varNodeIds.get(term.varName);
      if (!sourceId) continue;

      const edgeId = `edge-obj-${term.varName}-${nextId()}`;
      const edge: BuilderEdge = {
        id: edgeId,
        source: sourceId,
        target: objectiveNodeId,
        type: "coefficient",
        data: { coefficient: term.coefficient } as CoefficientEdgeData,
      };
      edges.push(edge);
    }
  } catch (err) {
    console.warn("[deserializer] Failed to parse objective expression:", problem.objective.expression, err);
  }

  for (let i = 0; i < problem.constraints.length; i++) {
    const constraint = problem.constraints[i];
    const constraintNodeId = `constraint-${i}`;

    let parsed: ParsedConstraint | null = null;
    try {
      parsed = parseConstraintExpression(constraint.expression);
    } catch (err) {
      console.warn("[deserializer] Failed to parse constraint expression:", constraint.expression, err);
    }

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
      for (const term of parsed.terms) {
        const sourceId = varNodeIds.get(term.varName);
        if (!sourceId) continue;

        const edgeId = `edge-c${i}-${term.varName}-${nextId()}`;
        const edge: BuilderEdge = {
          id: edgeId,
          source: sourceId,
          target: constraintNodeId,
          type: "coefficient",
          data: { coefficient: term.coefficient } as CoefficientEdgeData,
        };
        edges.push(edge);
      }
    }
  }

  const { nodes: layoutedNodes, edges: layoutedEdges } = applyDagreLayout(nodes, edges);

  return {
    nodes: layoutedNodes as BuilderNode[],
    edges: layoutedEdges as BuilderEdge[],
  };
}
