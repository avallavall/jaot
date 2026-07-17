import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";

import { LiveSolvePanel } from "../LiveSolvePanel";
import { IDLE_SOLVE_SESSION, type SolveSession } from "../../../store/createModelProjectStore";

function session(overrides: Partial<SolveSession>): SolveSession {
  return { ...IDLE_SOLVE_SESSION, ...overrides };
}

describe("LiveSolvePanel (presentational)", () => {
  it("shows the waiting state while running with no incumbents yet", () => {
    render(<LiveSolvePanel session={session({ status: "running" })} />);
    expect(screen.getByText("studio.liveRunning")).toBeInTheDocument();
    expect(screen.getByText("studio.liveWaiting")).toBeInTheDocument();
  });

  it("shows live metrics (not a chart) when incumbents streamed (SCIP)", () => {
    const points = [
      { iteration: 1, objective: 10, gap: 0.5, timestamp: 100 },
      { iteration: 2, objective: 8, gap: 0, timestamp: 200 },
    ];
    render(<LiveSolvePanel session={session({ status: "done", points })} />);
    expect(screen.getByText("studio.liveDone")).toBeInTheDocument();
    // A2: the flat convergence chart is gone; the honest live metrics remain.
    expect(screen.getByText("studio.liveNodes")).toBeInTheDocument();
    expect(screen.getByText("studio.liveIncumbents")).toBeInTheDocument();
    expect(screen.queryByTestId("chart")).not.toBeInTheDocument();
  });

  it("shows a clean final-result summary when the solver did NOT stream (HiGHS)", () => {
    const result = {
      status: "optimal",
      objective_value: 8,
      solution: { x1: 8 },
      solver_used: "highs",
      solve_time_seconds: 0.01,
    } as unknown as SolveSession["result"];
    render(<LiveSolvePanel session={session({ status: "done", points: [], result })} />);
    expect(screen.getByText("studio.liveDone")).toBeInTheDocument();
    // No empty live box / no "waiting"; a clean final summary instead.
    expect(screen.queryByTestId("chart")).not.toBeInTheDocument();
    expect(screen.queryByText("studio.liveWaiting")).not.toBeInTheDocument();
    expect(screen.getByText("studio.solveStatusLabel")).toBeInTheDocument();
    expect(screen.getByText("studio.solveSolverLabel")).toBeInTheDocument();
    expect(screen.getByText("optimal")).toBeInTheDocument();
  });
});
