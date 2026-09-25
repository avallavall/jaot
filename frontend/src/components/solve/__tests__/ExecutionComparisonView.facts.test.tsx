/**
 * The comparison says which solver ran each side, what it concluded and the
 * objective it reached, and an unchanged objective is not painted red.
 *
 * Found driving /solve/executions/compare (2026-09-25): the page showed neither
 * run's solver, status or objective, and "Objective Delta +0" was red on a
 * maximize model, because only a positive change counted as an improvement.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import type { ModelExecution } from "@/lib/types";

vi.mock("next-intl", () => ({
  useTranslations: (ns: string) =>
    Object.assign((key: string) => `${ns}.${key}`, {
      rich: (key: string) => `${ns}.${key}`,
      has: () => true,
    }),
  useNow: () => new Date(0),
  useFormatter: () => ({}),
  useLocale: () => "en",
}));

import { ExecutionComparisonView, formatObjDelta } from "../ExecutionComparisonView";

function aRun(overrides: Partial<ModelExecution> = {}): ModelExecution {
  return {
    id: "exe_aaaaaaaaaaaa",
    model_project_id: "mp_mknap",
    organization_model_id: null,
    status: "completed",
    solver_status: "optimal",
    solver_name: "jaos",
    objective_value: 6412,
    created_at: "2026-09-25T00:08:02Z",
    execution_time_ms: 63,
    input_data: { objective: { sense: "maximize", expression: "x" } },
    result_data: {
      status: "optimal",
      objective_value: 6412,
      solve_time_seconds: 0.06,
      warm_start_used: false,
      solution: { x: 1 },
      solver_used: "jaos",
    },
    ...overrides,
  } as ModelExecution;
}

describe("the comparison of two runs", () => {
  // CONTRACT-TEST: each side names its solver, verdict and objective
  it("names each run's solver, verdict and objective", () => {
    const scip = aRun({
      id: "exe_bbbbbbbbbbbb",
      solver_name: "scip",
      solver_status: "time_limit",
      result_data: { ...aRun().result_data!, solver_used: "scip" },
    });

    render(<ExecutionComparisonView executionA={aRun()} executionB={scip} />);

    const [a, b] = screen.getAllByTestId("comparison-run-facts");
    expect(a.textContent).toContain("JAOS");
    expect(a.textContent).toContain("solverCompare.status.optimal");
    expect(a.textContent).toContain("6,412");
    expect(b.textContent).toContain("SCIP");
    expect(b.textContent).toContain("solverCompare.status.time_limit");
  });

  it("paints an unchanged objective neutral, on a maximize model too", () => {
    expect(formatObjDelta(0, "maximize", 6412).color).toBe("text-muted-foreground");
    expect(formatObjDelta(0, "minimize", 6412).color).toBe("text-muted-foreground");
    expect(formatObjDelta(1e-12, "maximize", 6412).color).toBe("text-muted-foreground");
  });

  it("still paints a real change by its direction", () => {
    expect(formatObjDelta(5, "maximize", 6412).color).toContain("green");
    expect(formatObjDelta(-5, "maximize", 6412).color).toContain("red");
    expect(formatObjDelta(-5, "minimize", 6412).color).toContain("green");
  });
});
