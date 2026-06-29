import { describe, it, expect } from "vitest";
import type { OptimizationProblem } from "@/lib/types";
import { solveBlockedReason } from "../solve-precondition";

function makeProblem(partial: Partial<OptimizationProblem>): OptimizationProblem {
  return {
    variables: [],
    objective: { sense: "minimize", expression: "" },
    constraints: [],
    ...partial,
  } as OptimizationProblem;
}

const oneVar = [{ name: "x", type: "continuous" }] as OptimizationProblem["variables"];

describe("solveBlockedReason", () => {
  it("blocks when there are no variables", () => {
    expect(solveBlockedReason(makeProblem({ variables: [] }))).toBe("noVariables");
  });

  it("blocks when the objective expression is empty or whitespace", () => {
    expect(
      solveBlockedReason(
        makeProblem({ variables: oneVar, objective: { sense: "minimize", expression: "   " } })
      )
    ).toBe("noObjective");
  });

  it("allows a model with a variable and a non-empty objective", () => {
    expect(
      solveBlockedReason(
        makeProblem({ variables: oneVar, objective: { sense: "maximize", expression: "x" } })
      )
    ).toBeNull();
  });
});
