/**
 * A saved multi-objective run, on its own page and in the history.
 *
 * Found driving the app (2026-09-25): the run's page said "Optimal solution
 * proven" over a row of dashes and showed no point of the front, and the
 * history listed it as Model "External", Result "-". The history also printed
 * "6412.00" on a Spanish page.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import React from "react";

const { getExecution, getAllExecutions } = vi.hoisted(() => ({
  getExecution: vi.fn(),
  getAllExecutions: vi.fn(),
}));

vi.mock("next-intl", () => ({
  useTranslations: (ns: string) => {
    const t = (key: string, values?: Record<string, unknown>) =>
      `${ns}.${key}${values ? ` ${JSON.stringify(values)}` : ""}`;
    return Object.assign(t, { rich: t, has: () => true });
  },
  useLocale: () => "es",
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ executionId: "exe_front" }),
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
}));

vi.mock("@/i18n/navigation", () => ({
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/lib/api", () => ({
  api: { getExecution, getAllExecutions },
  ApiError: class ApiError extends Error {},
}));

vi.mock("@/hooks/useSolvers", () => ({ useSolverCapabilities: () => undefined }));

vi.mock("@/components/solve/ParetoChart", () => ({
  ParetoChart: ({ result }: { result: { pareto_points: Array<{ f1: number; f2: number }> } }) => (
    <ul data-testid="pareto-chart">
      {result.pareto_points.map((p) => (
        <li key={`${p.f1}-${p.f2}`}>{`${p.f1}/${p.f2}`}</li>
      ))}
    </ul>
  ),
}));

vi.mock("@/components/solve/ExportButtons", () => ({ ExportButtons: () => null }));

import ExecutionDetailPage from "../[executionId]/page";
import ExecutionsPage from "../page";

const FRONT_RUN = {
  id: "exe_front",
  organization_model_id: null,
  status: "completed",
  solver_status: "pareto_front",
  solver_name: "jaos",
  objective_value: null,
  execution_time_ms: 100,
  origin: "manual",
  created_at: "2026-09-25T00:13:34Z",
  input_data: { name: "profit_vs_emissions" },
  result_data: {
    objective_value: null,
    solver_status: "pareto_front",
    solver_used: "jaos",
    multi_objective: {
      pareto_points: [
        { f1: 44, f2: 34, solution: { x: 3, y: 7 }, objective_values: { P: 44, E: 34 } },
        { f1: 12, f2: 8, solution: { x: 4, y: 0 }, objective_values: { P: 12, E: 8 } },
      ],
      mode: "epsilon",
      n_solved: 2,
      labels: ["P", "E"],
    },
  },
};

describe("a saved multi-objective run", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // CONTRACT-TEST: a multi-objective run's page shows its front
  it("shows the front and says what kind of run it was", async () => {
    getExecution.mockResolvedValue(FRONT_RUN);

    render(<ExecutionDetailPage />);

    expect((await screen.findByTestId("execution-kind-badge")).textContent).toBe(
      "solve.execution.multiObjective.badge",
    );
    expect(screen.getByTestId("execution-solver-status").textContent).toBe(
      'solve.execution.multiObjective.status {"count":2}',
    );
    const points = within(screen.getByTestId("pareto-chart")).getAllByRole("listitem");
    expect(points.map((p) => p.textContent)).toEqual(["44/34", "12/8"]);
    // Nothing that reads one solution: no proven optimum over a row of dashes.
    expect(screen.queryByText("solve.execution.solveSummary")).toBeNull();
  });

  it("is named in the history, with its result", async () => {
    getAllExecutions.mockResolvedValue({
      items: [
        { ...FRONT_RUN, result_data: undefined, input_data: undefined },
        {
          id: "exe_single",
          organization_model_id: null,
          status: "completed",
          solver_status: "optimal",
          objective_value: 6412,
          execution_time_ms: 1234,
          origin: "manual",
          created_at: "2026-09-25T00:08:02Z",
        },
      ],
      total: 2,
    });

    render(<ExecutionsPage />);

    expect((await screen.findByTestId("execution-result-front")).textContent).toBe(
      "solve.executions.paretoFront",
    );
    expect(screen.getByText("solve.executions.multiObjectiveRun")).toBeInTheDocument();
    // In the page's language: "6412.00" on a Spanish page read wrong.
    expect(screen.getByTestId("execution-objective").textContent).toBe("6412,00");
    expect(screen.getByText('solve.executions.milliseconds {"ms":"1234"}')).toBeInTheDocument();
  });
});
