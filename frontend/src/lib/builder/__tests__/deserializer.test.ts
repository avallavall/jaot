import { describe, it, expect } from "vitest";
import { deserializeFromOptimizationProblem } from "../deserializer";
import { serializeToOptimizationProblem } from "../serializer";
import { constraintExpressionsEquivalent, linearExpressionsEquivalent } from "../linear";
import type { OptimizationProblem } from "@/lib/types";
import type { ConstraintNode } from "../types";
import { TREASURY_PROD } from "./fixtures/treasury-prod";

/** The prod Treasury model in miniature — the shapes the old parser mangled:
 * variables on the RHS, constant arithmetic, recurrences, a binary toggle. */
const TREASURY: OptimizationProblem = {
  variables: [
    { name: "cash_1", type: "continuous", lower_bound: 15000 },
    { name: "cash_2", type: "continuous", lower_bound: 15000 },
    { name: "borrow_1", type: "continuous", lower_bound: 0, upper_bound: 100000 },
    { name: "borrow_2", type: "continuous", lower_bound: 0, upper_bound: 100000 },
    { name: "invest_1", type: "continuous", lower_bound: 0 },
    { name: "invest_2", type: "continuous", lower_bound: 0, upper_bound: 0 },
    { name: "early_pay", type: "binary", lower_bound: 0, upper_bound: 1 },
  ],
  objective: { sense: "maximize", expression: "cash_2" },
  constraints: [
    {
      name: "balance_1",
      expression: "cash_1 == 30000 + 60000 - 50000 + borrow_1 - invest_1",
    },
    {
      name: "balance_2",
      expression:
        "cash_2 == cash_1 + 45000 - 75000 + 1.002*invest_1 - invest_2 + borrow_2 - 39200*early_pay",
    },
    { name: "repay_limit", expression: "invest_2 <= borrow_1" },
    { name: "closed", expression: "borrow_2 == 0" },
  ],
};

describe("deserializeFromOptimizationProblem — fidelity", () => {
  it("round-trips the Treasury shapes exactly (regression: prod 2026-07-31)", () => {
    const canvas = deserializeFromOptimizationProblem(TREASURY);
    expect(canvas.faithful).toBe(true);

    // The old parser left balance_2 an edge-less `<= 0` stub and truncated
    // balance_1 to `== 30000`. Every row must now carry its full term set.
    const byName = new Map(
      canvas.nodes
        .filter((n): n is ConstraintNode => n.type === "constraint")
        .map((n) => [n.data.name, n])
    );
    const balance1 = byName.get("balance_1")!;
    expect(balance1.data.operator).toBe("==");
    expect(balance1.data.rhs).toBe(40000);
    expect(canvas.edges.filter((e) => e.target === balance1.id)).toHaveLength(3);

    const balance2 = byName.get("balance_2")!;
    expect(balance2.data.rhs).toBe(-30000);
    expect(canvas.edges.filter((e) => e.target === balance2.id)).toHaveLength(6);

    // Serializing back denotes the SAME model, row by row.
    const rebuilt = serializeToOptimizationProblem(canvas.nodes, canvas.edges);
    expect(rebuilt.variables).toHaveLength(TREASURY.variables.length);
    expect(
      linearExpressionsEquivalent(rebuilt.objective.expression, TREASURY.objective.expression)
    ).toBe(true);
    expect(rebuilt.constraints).toHaveLength(TREASURY.constraints.length);
    for (let i = 0; i < rebuilt.constraints.length; i++) {
      expect(
        constraintExpressionsEquivalent(
          rebuilt.constraints[i].expression,
          TREASURY.constraints[i].expression
        ),
        `constraint ${TREASURY.constraints[i].name}`
      ).toBe(true);
    }
  });

  it("keeps variable types and bounds", () => {
    const canvas = deserializeFromOptimizationProblem(TREASURY);
    const rebuilt = serializeToOptimizationProblem(canvas.nodes, canvas.edges);
    const byName = new Map(rebuilt.variables.map((v) => [v.name, v]));
    expect(byName.get("early_pay")!.type).toBe("binary");
    expect(byName.get("invest_2")!.upper_bound).toBe(0);
    expect(byName.get("cash_1")!.lower_bound).toBe(15000);
  });

  it("flags a nonlinear constraint as unfaithful instead of pretending", () => {
    const canvas = deserializeFromOptimizationProblem({
      ...TREASURY,
      constraints: [{ name: "nl", expression: "cash_1 * borrow_1 <= 10" }],
    });
    expect(canvas.faithful).toBe(false);
  });

  it("flags an objective constant as unfaithful (no edge can carry it)", () => {
    const canvas = deserializeFromOptimizationProblem({
      ...TREASURY,
      objective: { sense: "maximize", expression: "cash_2 + 100" },
    });
    expect(canvas.faithful).toBe(false);
  });

  it("flags a term over an undeclared variable as unfaithful", () => {
    const canvas = deserializeFromOptimizationProblem({
      ...TREASURY,
      constraints: [{ name: "ghost", expression: "cash_1 + ghost <= 10" }],
    });
    expect(canvas.faithful).toBe(false);
  });

  it("round-trips the REAL prod Treasury model verbatim (31 vars, 19 constraints)", () => {
    const canvas = deserializeFromOptimizationProblem(TREASURY_PROD);
    expect(canvas.faithful).toBe(true);

    const rebuilt = serializeToOptimizationProblem(canvas.nodes, canvas.edges);
    expect(rebuilt.variables).toHaveLength(31);
    expect(rebuilt.constraints).toHaveLength(19);
    expect(
      linearExpressionsEquivalent(
        rebuilt.objective.expression,
        TREASURY_PROD.objective.expression
      )
    ).toBe(true);
    for (let i = 0; i < rebuilt.constraints.length; i++) {
      expect(
        constraintExpressionsEquivalent(
          rebuilt.constraints[i].expression,
          TREASURY_PROD.constraints[i].expression
        ),
        `constraint ${TREASURY_PROD.constraints[i].name}`
      ).toBe(true);
    }
  });
});
