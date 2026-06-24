// Converts an LLM Formulation into BuilderNode[] + BuilderEdge[] for the visual builder canvas.

import type { BuilderNode, BuilderEdge, VariableNode, ConstraintNode, ObjectiveNode } from "@/lib/builder/types";
import type { Formulation } from "@/lib/llm-types";

/**
 * Extract variable coefficients from a linear expression like "2*x + 3*y" or "-x + 2*y".
 * Standalone trailing numbers (RHS) are NOT treated as variables.
 */
export function parseTerms(expression: string): Map<string, number> {
  const terms = new Map<string, number>();
  const regex = /([+-]?\s*\d*\.?\d*)\s*\*?\s*([a-zA-Z_][a-zA-Z0-9_]*)/g;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(expression)) !== null) {
    const coeffStr = match[1].replace(/\s/g, "");
    let coeff: number;

    if (coeffStr === "" || coeffStr === "+") {
      coeff = 1;
    } else if (coeffStr === "-") {
      coeff = -1;
    } else {
      coeff = parseFloat(coeffStr);
    }

    if (isNaN(coeff)) coeff = 1;

    const varName = match[2];
    terms.set(varName, (terms.get(varName) ?? 0) + coeff);
  }

  return terms;
}

/** Split a constraint expression on its operator, parse LHS terms, extract RHS number. */
export function parseConstraintExpression(expression: string): {
  lhsTerms: Map<string, number>;
  operator: "<=" | ">=" | "==";
  rhs: number;
} {
  let operator: "<=" | ">=" | "==" = "<=";
  let parts: string[];

  if (expression.includes(">=")) {
    operator = ">=";
    parts = expression.split(">=");
  } else if (expression.includes("<=")) {
    operator = "<=";
    parts = expression.split("<=");
  } else if (expression.includes("==")) {
    operator = "==";
    parts = expression.split("==");
  } else if (expression.includes("=")) {
    operator = "==";
    parts = expression.split("=");
  } else {
    // No operator found — entire expression is LHS, RHS = 0.
    return {
      lhsTerms: parseTerms(expression),
      operator: "<=",
      rhs: 0,
    };
  }

  const lhs = parts[0]?.trim() ?? "";
  const rhsStr = parts[parts.length - 1]?.trim() ?? "0";
  const rhs = parseFloat(rhsStr);

  return {
    lhsTerms: parseTerms(lhs),
    operator,
    rhs: isNaN(rhs) ? 0 : rhs,
  };
}

/** Patterns that indicate parametric notation the canvas cannot represent. */
const PARAMETRIC_PATTERNS = [
  /\bsum_/i,
  /\bprod_/i,
  /\bfor\s+all\b/i,
  /\bfor\s+each\b/i,
  /\\sum\b/,
  /\\prod\b/,
  /\bSigma\b/,
  /\bPi\b/,
];

/** True if any expression uses parametric notation the canvas cannot represent. */
export function isParametricFormulation(formulation: Formulation): boolean {
  const expressions = [
    formulation.objective.expression,
    ...formulation.constraints.map((c) => c.expression),
  ];

  // Declared variable names — used to filter false positives like x_1.
  const varNames = new Set(formulation.variables.map((v) => v.name));

  for (const expr of expressions) {
    for (const pattern of PARAMETRIC_PATTERNS) {
      if (pattern.test(expr)) return true;
    }

    // x[i] patterns suggest indexed sets — parametric unless x is a declared variable.
    const indexPattern = /([a-zA-Z_]\w*)\[([a-zA-Z_]\w*)\]/g;
    let match: RegExpExecArray | null;
    while ((match = indexPattern.exec(expr)) !== null) {
      if (!varNames.has(match[0]) && !varNames.has(match[1])) {
        return true;
      }
    }
  }

  return false;
}

type ConversionResult =
  | { nodes: BuilderNode[]; edges: BuilderEdge[] }
  | { error: string };

/** Returns an error object if the formulation uses parametric notation. */
export function formulationToCanvas(formulation: Formulation): ConversionResult {
  if (isParametricFormulation(formulation)) {
    return {
      error:
        "This formulation uses parametric notation and cannot be opened in the visual builder. Try asking the AI to reformulate with explicit variables.",
    };
  }

  const nodes: BuilderNode[] = [];
  const edges: BuilderEdge[] = [];

  const varNameToId = new Map<string, string>();

  formulation.variables.forEach((v, i) => {
    const id = `var-${i}`;
    varNameToId.set(v.name, id);

    const node: VariableNode = {
      id,
      type: "variable",
      position: { x: 100, y: i * 140 },
      data: {
        name: v.name,
        type: v.type,
        lower_bound: v.lower_bound,
        upper_bound: v.upper_bound,
      },
    };
    nodes.push(node);
  });

  formulation.constraints.forEach((c, i) => {
    const id = `con-${i}`;
    const parsed = parseConstraintExpression(c.expression);

    let lhsExpression = c.expression;
    const opMatch = c.expression.match(/(<=|>=|==|=)/);
    if (opMatch && opMatch.index !== undefined) {
      lhsExpression = c.expression.slice(0, opMatch.index).trim();
    }

    const node: ConstraintNode = {
      id,
      type: "constraint",
      position: { x: 500, y: i * 140 },
      data: {
        name: c.name,
        operator: parsed.operator,
        rhs: parsed.rhs,
        formula: lhsExpression,
      },
    };
    nodes.push(node);

    for (const [varName, coefficient] of parsed.lhsTerms) {
      const sourceId = varNameToId.get(varName);
      if (sourceId) {
        edges.push({
          id: `edge-${sourceId}-${id}`,
          source: sourceId,
          target: id,
          data: { coefficient },
        });
      }
    }
  });

  const objId = "obj-0";
  const objTerms = parseTerms(formulation.objective.expression);

  const objNode: ObjectiveNode = {
    id: objId,
    type: "objective",
    position: { x: 500, y: (formulation.constraints.length + 1) * 140 },
    data: {
      sense: formulation.objective.sense,
      formula: formulation.objective.expression,
    },
  };
  nodes.push(objNode);

  for (const [varName, coefficient] of objTerms) {
    const sourceId = varNameToId.get(varName);
    if (sourceId) {
      edges.push({
        id: `edge-${sourceId}-${objId}`,
        source: sourceId,
        target: objId,
        data: { coefficient },
      });
    }
  }

  return { nodes, edges };
}
