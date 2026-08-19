import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";

/**
 * The response to a custom solve carries `solver_used`, `auto_route_reason` and
 * a full sensitivity block with shadow prices and reduced costs. None of it
 * reached the screen: the panel showed the status, the objective, the seconds
 * and the variable values, and never said which solver produced them — which
 * under "Auto" is the only place the routing is recorded.
 */

const { solve, RESULT } = vi.hoisted(() => ({
  solve: vi.fn(),
  RESULT: {
    execution_id: "exe_1",
    status: "optimal",
    objective_value: 63,
    solve_time_seconds: 0.012,
    solution: { x: 3, y: 2 },
    variables: [],
    solver_used: "scip",
    auto_route_reason: "milp_routed_to_scip",
    sensitivity: {
      constraints: [
        { name: "c1", shadow_price: 2.5, is_binding: true, slack: 0 },
        { name: "c2", shadow_price: 0, is_binding: false, slack: 4 },
      ],
      variables: [],
    },
  },
}));

vi.mock("@/lib/api", () => ({
  api: { solve, validateProblem: vi.fn() },
}));

vi.mock("@/hooks/useSolvers", () => ({
  useSolvers: () => ({
    solverName: "auto",
    setSolverName: vi.fn(),
    availableSolvers: [],
    solversLoading: false,
  }),
  useSolverCapabilities: () => undefined,
}));

vi.mock("@/components/solve/SolverSelect", () => ({
  SolverSelect: () => null,
}));

// recharts needs a non-zero layout in jsdom; the sensitivity panel draws a chart.
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ width: 800, height: 400 }}>{children}</div>
    ),
  };
});

import CustomSolvePage from "../custom/page";

async function solveOnce(result: Record<string, unknown>) {
  solve.mockResolvedValueOnce(result);
  render(<CustomSolvePage />);
  fireEvent.click(screen.getByText("solve.custom.solve"));
  await waitFor(() => expect(solve).toHaveBeenCalled());
}

describe("what a custom solve reports back", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // CONTRACT-TEST: the answer names the solver that produced it
  it("names the solver that ran, and says when it was chosen automatically", async () => {
    await solveOnce(RESULT);

    const tile = await screen.findByTestId("custom-solver-used");
    expect(tile.textContent).toContain("SCIP");
    expect(tile.textContent).toContain("solve.custom.autoRouted");
  });

  it("says nothing about routing when the user picked the solver", async () => {
    await solveOnce({ ...RESULT, auto_route_reason: null });

    const tile = await screen.findByTestId("custom-solver-used");
    expect(tile.textContent).toContain("SCIP");
    expect(tile.textContent).not.toContain("solve.custom.autoRouted");
  });

  // CONTRACT-TEST: shadow prices the response carries reach the screen
  it("shows the sensitivity the response carries", async () => {
    await solveOnce(RESULT);

    expect(await screen.findByTestId("custom-sensitivity")).toBeInTheDocument();
  });

  it("shows no sensitivity section for a solver that reported none", async () => {
    await solveOnce({ ...RESULT, sensitivity: null });

    await screen.findByTestId("custom-solver-used");
    expect(screen.queryByTestId("custom-sensitivity")).not.toBeInTheDocument();
  });
});
