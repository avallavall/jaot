import { describe, it, expect } from "vitest";
import type { Formulation } from "@/lib/llm-types";
import { isRealFormulation, humanizeProblemName } from "../formulation-adopt";

function makeFormulation(overrides: Partial<Formulation> = {}): Formulation {
  return {
    summary: "",
    variables: [
      { name: "x", type: "continuous", lower_bound: 0, upper_bound: null, description: "" },
    ],
    constraints: [],
    objective: { sense: "minimize", expression: "x", description: "" },
    problem_name: "my_model",
    ...overrides,
  };
}

describe("isRealFormulation", () => {
  it("accepts a model with variables", () => {
    expect(isRealFormulation(makeFormulation())).toBe(true);
  });

  it("rejects a refusal (not_applicable)", () => {
    expect(isRealFormulation(makeFormulation({ problem_name: "not_applicable" }))).toBe(false);
  });

  it("rejects a variable-less answer (a question / diagnosis)", () => {
    expect(isRealFormulation(makeFormulation({ variables: [] }))).toBe(false);
  });
});

describe("humanizeProblemName", () => {
  it("title-cases a snake_case name", () => {
    expect(humanizeProblemName("vehicle_routing_problem")).toBe("Vehicle Routing Problem");
  });

  it("handles a single token", () => {
    expect(humanizeProblemName("knapsack")).toBe("Knapsack");
  });
});
