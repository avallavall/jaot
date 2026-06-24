import { describe, it, expect } from "vitest";
import { estimateCredits } from "@/components/llm/CreditEstimate";
import type { Formulation } from "@/lib/llm-types";

function makeFormulation(
  vars: Array<{ type: "continuous" | "integer" | "binary" }>,
  constraintCount: number
): Formulation {
  return {
    summary: "test",
    problem_name: "test",
    variables: vars.map((v, i) => ({
      name: `x_${i}`,
      type: v.type,
      lower_bound: 0,
      upper_bound: null,
      description: "",
    })),
    constraints: Array.from({ length: constraintCount }, (_, i) => ({
      name: `c_${i}`,
      expression: `x_0 <= ${i + 1}`,
      description: "",
    })),
    objective: { sense: "minimize" as const, expression: "x_0", description: "" },
  };
}

describe("estimateCredits", () => {
  it("returns base cost of 1 for minimal problem", () => {
    // 1 continuous var, 0 constraints: 1 + 0.1 + 0 + 0 + 0 = 1.1 -> rounds to 1
    const f = makeFormulation([{ type: "continuous" }], 0);
    expect(estimateCredits(f)).toBe(1);
  });

  it("applies integer variable penalty", () => {
    // 1 integer var, 1 constraint: 1 + 0.1 + 0.3 + 0.05 = 1.45 -> rounds to 1
    const f = makeFormulation([{ type: "integer" }], 1);
    expect(estimateCredits(f)).toBe(1);
  });

  it("applies binary variable penalty", () => {
    // 5 binary vars, 3 constraints: 1 + 0.5 + 1.0 + 0.15 = 2.65 -> rounds to 3
    const f = makeFormulation(
      Array.from({ length: 5 }, () => ({ type: "binary" as const })),
      3
    );
    expect(estimateCredits(f)).toBe(3);
  });

  it("handles continuous-only variables", () => {
    // 10 continuous, 5 constraints: 1 + 1.0 + 0 + 0 + 0.25 = 2.25 -> rounds to 2
    const f = makeFormulation(
      Array.from({ length: 10 }, () => ({ type: "continuous" as const })),
      5
    );
    expect(estimateCredits(f)).toBe(2);
  });

  it("enforces minimum of 1 credit", () => {
    // 0 vars, 0 constraints: 1 + 0 + 0 + 0 = 1
    const f = makeFormulation([], 0);
    expect(estimateCredits(f)).toBeGreaterThanOrEqual(1);
  });

  it("calculates correctly for large problem", () => {
    // 50 integer vars, 30 constraints: 1 + 5.0 + 15.0 + 1.5 = 22.5 -> rounds to 23
    const f = makeFormulation(
      Array.from({ length: 50 }, () => ({ type: "integer" as const })),
      30
    );
    expect(estimateCredits(f)).toBe(23);
  });

  it("handles mixed variable types", () => {
    // 2 continuous + 2 integer + 2 binary, 4 constraints
    // 1 + 6*0.1 + 2*0.3 + 2*0.2 + 4*0.05 = 1 + 0.6 + 0.6 + 0.4 + 0.2 = 2.8 -> rounds to 3
    const f = makeFormulation(
      [
        { type: "continuous" },
        { type: "continuous" },
        { type: "integer" },
        { type: "integer" },
        { type: "binary" },
        { type: "binary" },
      ],
      4
    );
    expect(estimateCredits(f)).toBe(3);
  });
});
