/**
 * The multi-objective page sends the solver the user picked, asks for no
 * weights, and links to the run it saved.
 *
 * Found driving the page (2026-09-25): it had no solver picker and the server
 * ran SCIP whatever the request named; weighted mode asked for a weight per
 * objective and refused to solve unless they summed to 1, and the server never
 * read them; and the response had no execution id, so the page could not link
 * to the run it had just made.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";

const { solveMultiObjective } = vi.hoisted(() => ({ solveMultiObjective: vi.fn() }));

// The key path plus the values it was given, so an assertion can see both.
vi.mock("next-intl", () => ({
  useTranslations: (ns: string) => {
    const t = (key: string, values?: Record<string, unknown>) =>
      `${ns}.${key}${values ? ` ${JSON.stringify(values)}` : ""}`;
    return Object.assign(t, { rich: t, has: () => true });
  },
  useLocale: () => "en",
}));

vi.mock("@/lib/api", () => ({
  api: { solveMultiObjective },
  ApiError: class ApiError extends Error {},
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ activeWorkspaceId: null }),
}));

vi.mock("@/hooks/useSolvers", () => ({
  useSolvers: () => ({
    solverName: "jaos",
    setSolverName: vi.fn(),
    availableSolvers: [],
    solversLoading: false,
  }),
}));

vi.mock("@/components/solve/SolverSelect", () => ({
  SolverSelect: ({ solverName }: { solverName: string }) => (
    <div data-testid="solver-select">{solverName}</div>
  ),
}));

vi.mock("@/components/solve/ParetoChart", () => ({
  ParetoChart: () => <div data-testid="pareto-chart" />,
}));

vi.mock("@/components/solve/ImportSourcePanel", () => ({
  ImportSourcePanel: () => null,
}));

vi.mock("@/i18n/navigation", () => ({
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn(), warning: vi.fn() }),
}));

import MultiObjectivePage from "../multi-objective/page";

function fillObjectives() {
  fireEvent.change(screen.getByTestId("objective-expression-0"), {
    target: { value: "3*x + 5*y" },
  });
  fireEvent.change(screen.getByTestId("objective-expression-1"), {
    target: { value: "2*x + 4*y" },
  });
}

describe("the multi-objective page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    solveMultiObjective.mockResolvedValue({
      pareto_points: [
        { f1: 44, f2: 34, solution: { x: 3, y: 7 }, objective_values: {} },
        { f1: 12, f2: 8, solution: { x: 4, y: 0 }, objective_values: {} },
      ],
      mode: "weighted",
      n_solved: 2,
      labels: ["P", "E"],
      execution_id: "exe_saved",
      solver_used: "jaos",
    });
  });

  it("offers a solver picker", () => {
    render(<MultiObjectivePage />);

    expect(screen.getByTestId("solver-select")).toBeInTheDocument();
  });

  it("asks for no weights in weighted mode", () => {
    render(<MultiObjectivePage />);
    fireEvent.click(screen.getByText("solve.multiObjectiveConfig.weightedCombination"));

    // The only slider left is the number of points.
    expect(document.querySelectorAll('input[type="range"]')).toHaveLength(1);
    expect(screen.queryByText("solve.multiObjectiveConfig.weightsMustSum")).toBeNull();
  });

  // CONTRACT-TEST: the solver the user picked is the one the request names
  it("sends the picked solver and no weights, and links to the saved run", async () => {
    render(<MultiObjectivePage />);
    fireEvent.click(screen.getByText("solve.multiObjectiveConfig.weightedCombination"));
    fillObjectives();
    fireEvent.click(screen.getByTestId("solve-btn"));

    await waitFor(() => expect(solveMultiObjective).toHaveBeenCalled());
    const [problem, config] = solveMultiObjective.mock.calls[0];
    expect(problem.solver_name).toBe("jaos");
    expect(config.mode).toBe("weighted");
    for (const objective of config.objectives) {
      expect(objective.weight).toBeUndefined();
    }

    const link = (await screen.findByText("solve.multiObjective.openSavedRun")).closest("a");
    expect(link?.getAttribute("href")).toBe("/solve/executions/exe_saved");
    expect(screen.getByTestId("pareto-run-summary").textContent).toContain("JAOS");
  });
});
