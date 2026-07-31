import { describe, it, expect } from "vitest";
import {
  parseLinearSide,
  parseLinearConstraint,
  constraintExpressionsEquivalent,
  linearExpressionsEquivalent,
} from "../linear";

describe("parseLinearSide", () => {
  it("reads terms, folded constants and signed coefficients", () => {
    const side = parseLinearSide("cash_1 + 45000 - 75000 + 1.002*invest_1 - invest_2");
    expect(side).not.toBeNull();
    expect(side!.constant).toBe(-30000);
    expect(side!.terms).toEqual([
      { coefficient: 1, varName: "cash_1" },
      { coefficient: 1.002, varName: "invest_1" },
      { coefficient: -1, varName: "invest_2" },
    ]);
  });

  it("accepts implicit multiplication and sign chains", () => {
    expect(parseLinearSide("2 x")!.terms).toEqual([{ coefficient: 2, varName: "x" }]);
    expect(parseLinearSide("- -x")!.terms).toEqual([{ coefficient: 1, varName: "x" }]);
    expect(parseLinearSide("-0.008*debt_2")!.terms).toEqual([
      { coefficient: -0.008, varName: "debt_2" },
    ]);
  });

  it("reads a bare constant (the serializer's empty-expression '0')", () => {
    expect(parseLinearSide("0")).toEqual({ terms: [], constant: 0 });
  });

  it("declines anything it cannot represent exactly", () => {
    expect(parseLinearSide("x*y")).toBeNull(); // nonlinear
    expect(parseLinearSide("x*2")).toBeNull(); // unsupported ordering
    expect(parseLinearSide("2*(x + y)")).toBeNull(); // parentheses
    expect(parseLinearSide("x / 2")).toBeNull(); // division
    expect(parseLinearSide("x +")).toBeNull(); // dangling operator
    expect(parseLinearSide("x y")).toBeNull(); // two idents, no operator
    expect(parseLinearSide("")).toBeNull();
  });
});

describe("parseLinearConstraint", () => {
  it("reads the prod Treasury balance row exactly (variables on BOTH sides)", () => {
    // The row the old parser truncated to `cash_1 == 30000` in production.
    const parsed = parseLinearConstraint(
      "cash_1 == 30000 + 60000 - 50000 + borrow_1 - repay_1 - invest_1 - 0.008*debt_1"
    );
    expect(parsed).not.toBeNull();
    expect(parsed!.operator).toBe("==");
    expect(parsed!.rhs).toBe(40000);
    expect(parsed!.terms).toEqual([
      { coefficient: 1, varName: "cash_1" },
      { coefficient: -1, varName: "borrow_1" },
      { coefficient: 1, varName: "repay_1" },
      { coefficient: 1, varName: "invest_1" },
      { coefficient: 0.008, varName: "debt_1" },
    ]);
  });

  it("reads a pure variable-vs-variable row (the old parser dropped these to 0 <= 0)", () => {
    const parsed = parseLinearConstraint("repay_2 <= debt_1");
    expect(parsed).toEqual({
      terms: [
        { coefficient: 1, varName: "repay_2" },
        { coefficient: -1, varName: "debt_1" },
      ],
      operator: "<=",
      rhs: 0,
    });
  });

  it("cancels a variable appearing on both sides", () => {
    const parsed = parseLinearConstraint("x + y <= x + 4");
    expect(parsed).toEqual({ terms: [{ coefficient: 1, varName: "y" }], operator: "<=", rhs: 4 });
  });

  it("declines chained comparisons and missing operators", () => {
    expect(parseLinearConstraint("1 <= x <= 5")).toBeNull();
    expect(parseLinearConstraint("x + y")).toBeNull();
  });

  it("reads the trivial 0 <= 0 row", () => {
    expect(parseLinearConstraint("0 <= 0")).toEqual({ terms: [], operator: "<=", rhs: 0 });
  });
});

describe("equivalence", () => {
  it("ignores term order and constant placement", () => {
    expect(constraintExpressionsEquivalent("x + 2*y <= 10", "2*y <= 10 - x")).toBe(true);
    expect(constraintExpressionsEquivalent("x + 2*y <= 10", "x + 2*y >= 10")).toBe(false);
    expect(constraintExpressionsEquivalent("x + 2*y <= 10", "x + 2*y <= 11")).toBe(false);
    expect(constraintExpressionsEquivalent("x + 2*y <= 10", "x + 3*y <= 10")).toBe(false);
  });

  it("falls back to exact-string equality for unreadable expressions", () => {
    expect(constraintExpressionsEquivalent("f(x) <= 1", "f(x) <= 1")).toBe(true);
    expect(constraintExpressionsEquivalent("f(x) <= 1", "g(x) <= 1")).toBe(false);
  });

  it("compares objectives with constants counted", () => {
    expect(linearExpressionsEquivalent("2*x + y", "y + 2*x")).toBe(true);
    expect(linearExpressionsEquivalent("2*x + 1", "2*x")).toBe(false);
  });
});
