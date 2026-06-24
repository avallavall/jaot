import { describe, it, expect } from "vitest";
import {
  parseTerms,
  parseConstraintExpression,
  isParametricFormulation,
  formulationToCanvas,
} from "@/lib/builder/formulationToCanvas";
import type { Formulation } from "@/lib/llm-types";

// ============================================================
// parseTerms
// ============================================================

describe("parseTerms", () => {
  it("parses standard coefficients", () => {
    const terms = parseTerms("2*x + 3*y");
    expect(terms.get("x")).toBe(2);
    expect(terms.get("y")).toBe(3);
  });

  it("parses implicit coefficient of 1", () => {
    const terms = parseTerms("x + y");
    expect(terms.get("x")).toBe(1);
    expect(terms.get("y")).toBe(1);
  });

  it("parses negative coefficients", () => {
    const terms = parseTerms("-x + 2*y");
    expect(terms.get("x")).toBe(-1);
    expect(terms.get("y")).toBe(2);
  });

  it("parses expressions without spaces", () => {
    const terms = parseTerms("2*x+3*y");
    expect(terms.get("x")).toBe(2);
    expect(terms.get("y")).toBe(3);
  });

  it("parses decimal coefficients", () => {
    const terms = parseTerms("1.5*x + 0.3*y");
    expect(terms.get("x")).toBe(1.5);
    expect(terms.get("y")).toBe(0.3);
  });

  it("returns empty map for empty expression", () => {
    const terms = parseTerms("");
    expect(terms.size).toBe(0);
  });

  it("handles variables with underscores", () => {
    const terms = parseTerms("2*x_1 + 3*x_2");
    expect(terms.get("x_1")).toBe(2);
    expect(terms.get("x_2")).toBe(3);
  });

  it("accumulates same variable", () => {
    const terms = parseTerms("2*x + 3*x");
    expect(terms.get("x")).toBe(5);
  });
});

// ============================================================
// parseConstraintExpression
// ============================================================

describe("parseConstraintExpression", () => {
  it("parses <= constraint", () => {
    const result = parseConstraintExpression("2*x + 3*y <= 10");
    expect(result.operator).toBe("<=");
    expect(result.rhs).toBe(10);
    expect(result.lhsTerms.get("x")).toBe(2);
    expect(result.lhsTerms.get("y")).toBe(3);
  });

  it("parses >= constraint", () => {
    const result = parseConstraintExpression("x + y >= 5");
    expect(result.operator).toBe(">=");
    expect(result.rhs).toBe(5);
  });

  it("parses == constraint", () => {
    const result = parseConstraintExpression("x + y == 1");
    expect(result.operator).toBe("==");
    expect(result.rhs).toBe(1);
  });

  it("parses negative RHS", () => {
    const result = parseConstraintExpression("x <= -5");
    expect(result.rhs).toBe(-5);
  });

  it("parses single = as ==", () => {
    const result = parseConstraintExpression("x = 1");
    expect(result.operator).toBe("==");
    expect(result.rhs).toBe(1);
  });
});

// ============================================================
// isParametricFormulation
// ============================================================

describe("isParametricFormulation", () => {
  const baseFormulation: Formulation = {
    summary: "test",
    problem_name: "test",
    variables: [
      { name: "x", type: "continuous", lower_bound: 0, upper_bound: null, description: "" },
      { name: "y", type: "continuous", lower_bound: 0, upper_bound: null, description: "" },
    ],
    constraints: [{ name: "c1", expression: "x + y <= 10", description: "" }],
    objective: { sense: "minimize", expression: "x + y", description: "" },
  };

  it("returns false for simple LP", () => {
    expect(isParametricFormulation(baseFormulation)).toBe(false);
  });

  it("detects sum_j notation", () => {
    const f = {
      ...baseFormulation,
      objective: { ...baseFormulation.objective, expression: "sum_j c_j * x_j" },
    };
    expect(isParametricFormulation(f)).toBe(true);
  });

  it("detects 'for all' notation", () => {
    const f = {
      ...baseFormulation,
      constraints: [{ name: "c1", expression: "for all i: x_i <= 5", description: "" }],
    };
    expect(isParametricFormulation(f)).toBe(true);
  });

  it("detects LaTeX \\sum", () => {
    const f = {
      ...baseFormulation,
      objective: { ...baseFormulation.objective, expression: "\\sum_{i=1}^n x_i" },
    };
    expect(isParametricFormulation(f)).toBe(true);
  });

  it("allows normal variables like x_1", () => {
    const f: Formulation = {
      ...baseFormulation,
      variables: [
        { name: "x_1", type: "continuous", lower_bound: 0, upper_bound: null, description: "" },
        { name: "x_2", type: "continuous", lower_bound: 0, upper_bound: null, description: "" },
      ],
      constraints: [{ name: "c1", expression: "x_1 + x_2 <= 10", description: "" }],
      objective: { sense: "minimize", expression: "x_1 + x_2", description: "" },
    };
    expect(isParametricFormulation(f)).toBe(false);
  });
});

// ============================================================
// formulationToCanvas
// ============================================================

describe("formulationToCanvas", () => {
  const simpleLP: Formulation = {
    summary: "Simple LP",
    problem_name: "simple_lp",
    variables: [
      { name: "x", type: "continuous", lower_bound: 0, upper_bound: 10, description: "var x" },
      { name: "y", type: "integer", lower_bound: 0, upper_bound: null, description: "var y" },
    ],
    constraints: [
      { name: "budget", expression: "2*x + 3*y <= 12", description: "budget" },
      { name: "demand", expression: "x + y >= 2", description: "demand" },
    ],
    objective: { sense: "maximize", expression: "5*x + 4*y", description: "profit" },
  };

  it("produces correct node counts", () => {
    const result = formulationToCanvas(simpleLP);
    expect("nodes" in result).toBe(true);
    if (!("nodes" in result)) return;

    // 2 variables + 2 constraints + 1 objective = 5 nodes
    expect(result.nodes).toHaveLength(5);
  });

  it("produces correct edge counts", () => {
    const result = formulationToCanvas(simpleLP);
    expect("edges" in result).toBe(true);
    if (!("edges" in result)) return;

    // budget: x,y -> 2 edges. demand: x,y -> 2 edges. objective: x,y -> 2 edges = 6
    expect(result.edges).toHaveLength(6);
  });

  it("maps variable types correctly", () => {
    const result = formulationToCanvas(simpleLP);
    if (!("nodes" in result)) return;

    const varNodes = result.nodes.filter((n) => n.type === "variable");
    expect(varNodes[0].data).toMatchObject({ name: "x", type: "continuous" });
    expect(varNodes[1].data).toMatchObject({ name: "y", type: "integer" });
  });

  it("sets correct positions", () => {
    const result = formulationToCanvas(simpleLP);
    if (!("nodes" in result)) return;

    const varNodes = result.nodes.filter((n) => n.type === "variable");
    expect(varNodes[0].position).toEqual({ x: 100, y: 0 });
    expect(varNodes[1].position).toEqual({ x: 100, y: 140 });

    const conNodes = result.nodes.filter((n) => n.type === "constraint");
    expect(conNodes[0].position).toEqual({ x: 500, y: 0 });
    expect(conNodes[1].position).toEqual({ x: 500, y: 140 });
  });

  it("sets correct edge coefficients", () => {
    const result = formulationToCanvas(simpleLP);
    if (!("edges" in result)) return;

    // Find edge from x (var-0) to budget (con-0)
    const xToBudget = result.edges.find(
      (e) => e.source === "var-0" && e.target === "con-0"
    );
    expect(xToBudget?.data?.coefficient).toBe(2);

    // Find edge from y (var-1) to objective (obj-0)
    const yToObj = result.edges.find(
      (e) => e.source === "var-1" && e.target === "obj-0"
    );
    expect(yToObj?.data?.coefficient).toBe(4);
  });

  it("returns error for parametric formulation", () => {
    const parametric: Formulation = {
      summary: "Parametric",
      problem_name: "parametric",
      variables: [
        { name: "x", type: "continuous", lower_bound: 0, upper_bound: null, description: "" },
      ],
      constraints: [{ name: "c1", expression: "sum_j x_j <= 10", description: "" }],
      objective: { sense: "minimize", expression: "x", description: "" },
    };

    const result = formulationToCanvas(parametric);
    expect("error" in result).toBe(true);
  });

  it("maps constraint operator and rhs", () => {
    const result = formulationToCanvas(simpleLP);
    if (!("nodes" in result)) return;

    const conNodes = result.nodes.filter((n) => n.type === "constraint");
    expect(conNodes[0].data).toMatchObject({ operator: "<=", rhs: 12 });
    expect(conNodes[1].data).toMatchObject({ operator: ">=", rhs: 2 });
  });

  it("maps objective sense", () => {
    const result = formulationToCanvas(simpleLP);
    if (!("nodes" in result)) return;

    const objNode = result.nodes.find((n) => n.type === "objective");
    expect(objNode?.data).toMatchObject({ sense: "maximize" });
  });
});
