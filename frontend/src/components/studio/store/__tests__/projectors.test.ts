import { describe, it, expect } from "vitest";
import { canvasProjector } from "../projectors";
import type { OptimizationProblem } from "@/lib/types";

const PROBLEM: OptimizationProblem = {
  variables: [
    { name: "x", type: "continuous", lower_bound: 0 },
    { name: "y", type: "integer", lower_bound: 0, upper_bound: 5 },
  ],
  objective: { sense: "maximize", expression: "3*x + 2*y" },
  constraints: [{ name: "c1", expression: "x + y <= 4" }],
};

describe("canvasProjector round-trip", () => {
  it("preserves variables, objective sense and constraints through problem -> canvas -> problem", () => {
    const view = canvasProjector.fromProblem(PROBLEM);
    const back = canvasProjector.toProblem(view);

    expect(back.variables.map((v) => v.name).sort()).toEqual(["x", "y"]);
    const yVar = back.variables.find((v) => v.name === "y");
    expect(yVar?.type).toBe("integer");
    expect(back.objective.sense).toBe("maximize");
    expect(back.objective.expression).toContain("x");
    expect(back.objective.expression).toContain("y");
    expect(back.constraints).toHaveLength(1);
    expect(back.constraints[0].expression).toContain("<= 4");
  });
});
