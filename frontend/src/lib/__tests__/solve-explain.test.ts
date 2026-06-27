import { describe, it, expect } from "vitest";
import { deriveExplainState } from "../solve-explain";
import type { ModelExecution } from "@/lib/types";

type ResultDataLike = { status?: string; variables?: unknown[] };

function makeResult(
  status: string,
  solverStatus: string | undefined,
  resultData: ResultDataLike,
): ModelExecution {
  return {
    id: "exe_1",
    status,
    solver_status: solverStatus,
    result_data: resultData,
  } as unknown as ModelExecution;
}

describe("deriveExplainState", () => {
  it("returns an inert state for a null result", () => {
    expect(deriveExplainState(null)).toEqual({
      solverStatus: null,
      isInfeasible: false,
      hasSolution: false,
      canExplainSolution: false,
    });
  });

  it("explains an optimal sync solve (top-level solver_status)", () => {
    const s = deriveExplainState(
      makeResult("completed", "optimal", { status: "optimal", variables: [{}] }),
    );
    expect(s.canExplainSolution).toBe(true);
    expect(s.hasSolution).toBe(true);
    expect(s.isInfeasible).toBe(false);
  });

  it("flags an infeasible sync solve and offers no solution explainer", () => {
    const s = deriveExplainState(
      makeResult("completed", "infeasible", { status: "infeasible", variables: [] }),
    );
    expect(s.isInfeasible).toBe(true);
    expect(s.canExplainSolution).toBe(false);
    expect(s.hasSolution).toBe(false);
  });

  // Regression: async runs carry no top-level solver_status, so the gating must
  // read result_data.status (NOT the non-existent result_data.solver_status).
  it("explains an optimal async solve via result_data.status", () => {
    const s = deriveExplainState(
      makeResult("completed", undefined, { status: "optimal", variables: [{}] }),
    );
    expect(s.solverStatus).toBe("optimal");
    expect(s.canExplainSolution).toBe(true);
    expect(s.hasSolution).toBe(true);
  });

  it("flags an infeasible async solve via result_data.status", () => {
    const s = deriveExplainState(
      makeResult("completed", undefined, { status: "infeasible", variables: [] }),
    );
    expect(s.isInfeasible).toBe(true);
    expect(s.canExplainSolution).toBe(false);
  });

  it("treats a feasible solve as explainable", () => {
    const s = deriveExplainState(
      makeResult("completed", "feasible", { status: "feasible", variables: [{}] }),
    );
    expect(s.canExplainSolution).toBe(true);
  });

  it("reports no solution to explain when there are no variables", () => {
    const s = deriveExplainState(
      makeResult("completed", "optimal", { status: "optimal", variables: [] }),
    );
    expect(s.hasSolution).toBe(false);
  });
});
