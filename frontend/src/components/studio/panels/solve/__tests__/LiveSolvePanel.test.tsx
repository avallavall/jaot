import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";

import { LiveSolvePanel } from "../LiveSolvePanel";
import {
  IDLE_SOLVE_SESSION,
  type SolveSession,
} from "../../../store/createModelProjectStore";

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
    render(
      <LiveSolvePanel
        session={session({ status: "done", points: [], result })}
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

/**
 * v3.2 — a solver that streams nothing used to sit on "waiting for the first
 * incumbent" for the whole solve and then jump straight to the result. When the
 * listing tells us the solver does not stream, say that instead.
 */
describe("LiveSolvePanel progress capability", () => {
  const STREAMS = {
    sensitivity: true,
    warm_start: true,
    quadratic: true,
    progress: true,
  };
  const NO_STREAM = {
    sensitivity: false,
    warm_start: true,
    quadratic: true,
    progress: false,
  };

  it("explains the silence for a solver that does not stream", () => {
    render(
      <LiveSolvePanel
        session={session({ status: "running", solverName: "hexaly" })}
        capabilities={NO_STREAM}
      />,
    );
    expect(screen.getByText("studio.liveNoProgressStream")).toBeInTheDocument();
    expect(screen.queryByText("studio.liveWaiting")).not.toBeInTheDocument();
  });

  it("still waits for the first incumbent when the solver does stream", () => {
    render(
      <LiveSolvePanel
        session={session({ status: "running", solverName: "scip" })}
        capabilities={STREAMS}
      />,
    );
    expect(screen.getByText("studio.liveWaiting")).toBeInTheDocument();
    expect(
      screen.queryByText("studio.liveNoProgressStream"),
    ).not.toBeInTheDocument();
  });

  // Unknown capabilities (auto-routing, or a solver the listing does not carry)
  // must not claim anything about streaming.
  it("falls back to waiting when capabilities are unknown", () => {
    render(
      <LiveSolvePanel
        session={session({ status: "running", solverName: "auto" })}
      />,
    );
    expect(screen.getByText("studio.liveWaiting")).toBeInTheDocument();
    expect(
      screen.queryByText("studio.liveNoProgressStream"),
    ).not.toBeInTheDocument();
  });

  // The generic "some solvers stream, others don't" footnote hard-codes solver
  // names; it is only shown while we cannot name THIS solver's behaviour.
  it("drops the generic footnote once the solver's behaviour is known", () => {
    const { rerender } = render(
      <LiveSolvePanel
        session={session({ status: "running", solverName: "auto" })}
      />,
    );
    expect(screen.getByText("studio.liveStreamNote")).toBeInTheDocument();

    rerender(
      <LiveSolvePanel
        session={session({ status: "running", solverName: "scip" })}
        capabilities={STREAMS}
      />,
    );
    expect(screen.queryByText("studio.liveStreamNote")).not.toBeInTheDocument();
  });
});

describe("a run that finished without a solution", () => {
  function finished(status: string) {
    return session({
      status: "done",
      points: [],
      result: {
        status,
        objective_value: null,
        solver_used: "scip",
        solve_time_seconds: 0.02,
      } as unknown as SolveSession["result"],
    });
  }

  // CONTRACT-TEST: a finished run is never announced as solved unless it solved
  it.each(["infeasible", "unbounded", "error"])(
    "does not claim %s was solved",
    (verdict) => {
      render(<LiveSolvePanel session={finished(verdict)} />);
      expect(screen.queryByText("studio.liveDone")).not.toBeInTheDocument();
      expect(screen.getByText("studio.liveNoAnswer")).toBeInTheDocument();
    },
  );

  it.each(["optimal", "feasible"])("still says solved for %s", (verdict) => {
    render(<LiveSolvePanel session={finished(verdict)} />);
    expect(screen.getByText("studio.liveDone")).toBeInTheDocument();
    expect(screen.queryByText("studio.liveNoAnswer")).not.toBeInTheDocument();
  });

  it("keeps showing the metrics, so the verdict is still readable", () => {
    render(<LiveSolvePanel session={finished("infeasible")} />);
    expect(screen.getByText("studio.solveStatusLabel")).toBeInTheDocument();
    expect(screen.getByText("infeasible")).toBeInTheDocument();
  });

  it("says nothing new when the solver reported no status at all", () => {
    render(
      <LiveSolvePanel session={session({ status: "done", points: [] })} />,
    );
    expect(screen.getByText("studio.liveDone")).toBeInTheDocument();
  });
});
