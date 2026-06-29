import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

// recharts is heavy in jsdom — stub the chart.
vi.mock("@/components/solve/GapConvergenceChart", () => ({
  GapConvergenceChart: () => <div data-testid="chart" />,
}));

import { LiveSolvePanel } from "../LiveSolvePanel";
import { IDLE_SOLVE_SESSION, type SolveSession } from "../../../store/createModelProjectStore";

function session(overrides: Partial<SolveSession>): SolveSession {
  return { ...IDLE_SOLVE_SESSION, ...overrides };
}

describe("LiveSolvePanel (presentational)", () => {
  it("shows the waiting state while running with no incumbents yet", () => {
    render(
      <LiveSolvePanel session={session({ status: "running" })} objectiveSense="minimize" />,
    );
    expect(screen.getByText("studio.liveRunning")).toBeInTheDocument();
    expect(screen.getByText("studio.liveWaiting")).toBeInTheDocument();
    expect(screen.queryByTestId("chart")).not.toBeInTheDocument();
  });

  it("shows the convergence chart when incumbents streamed (SCIP)", () => {
    const points = [
      { iteration: 1, objective: 10, gap: 0.5, timestamp: 100 },
      { iteration: 2, objective: 8, gap: 0, timestamp: 200 },
    ];
    render(
      <LiveSolvePanel session={session({ status: "done", points })} objectiveSense="minimize" />,
    );
    expect(screen.getByText("studio.liveDone")).toBeInTheDocument();
    expect(screen.getByTestId("chart")).toBeInTheDocument();
  });

  it("shows a clean final-result summary when the solver did NOT stream (HiGHS)", () => {
    const result = {
      status: "optimal",
      objective_value: 8,
      solution: { x1: 8 },
      solver_used: "highs",
      solve_time_seconds: 0.01,
    } as unknown as SolveSession["result"];
    render(
      <LiveSolvePanel
        session={session({ status: "done", points: [], result })}
        objectiveSense="minimize"
      />,
    );
    expect(screen.getByText("studio.liveDone")).toBeInTheDocument();
    // No empty live box / no "waiting"; a clean final summary instead.
    expect(screen.queryByTestId("chart")).not.toBeInTheDocument();
    expect(screen.queryByText("studio.liveWaiting")).not.toBeInTheDocument();
    expect(screen.getByText("studio.solveStatusLabel")).toBeInTheDocument();
    expect(screen.getByText("studio.solveSolverLabel")).toBeInTheDocument();
    expect(screen.getByText("optimal")).toBeInTheDocument();
  });
});
