import React from "react";
import { render, screen, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

const { mockGetStatus, mockCancel } = vi.hoisted(() => ({
  mockGetStatus: vi.fn(),
  mockCancel: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: { getSolveAsyncStatus: mockGetStatus, cancelSolveAsync: mockCancel },
}));
// No real WebSocket in the test (avoids the WS-component render churn).
vi.mock("@/hooks/useWebSocket", () => ({
  useExecutionWebSocket: () => ({ isConnected: false }),
}));
// recharts is heavy in jsdom — stub the chart.
vi.mock("@/components/solve/GapConvergenceChart", () => ({
  GapConvergenceChart: () => <div data-testid="chart" />,
}));

import { LiveSolvePanel } from "../LiveSolvePanel";

// The REAL completed payload: `status:"completed"` and `result` is the Celery task
// envelope — the actual SolveResult is `result.result`.
const COMPLETED = {
  task_id: "t1",
  status: "completed",
  result: {
    status: "success",
    task_id: "t1",
    result: {
      status: "optimal",
      objective_value: 8,
      solution: { x1: 8 },
      progress_history: null,
    },
    solver_used: "highs",
  },
};

/** Inline `onComplete` arrow → a NEW identity on every render — exactly how SolvePanel passes it. */
function Harness({ cb }: { cb: (r: unknown) => void }) {
  return (
    <LiveSolvePanel
      taskId="t1"
      objectiveSense="minimize"
      onComplete={(r) => cb(r)}
      onError={() => {}}
    />
  );
}

describe("LiveSolvePanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("fires onComplete ONCE with the UNWRAPPED SolveResult and stays 'completed' across parent re-renders", async () => {
    mockGetStatus.mockResolvedValue(COMPLETED);
    const cb = vi.fn();
    const { rerender } = render(<Harness cb={cb} />);

    // The immediate poll resolves to "completed".
    await waitFor(() => expect(cb).toHaveBeenCalledTimes(1));
    expect(cb).toHaveBeenCalledWith(
      expect.objectContaining({ objective_value: 8, solution: { x1: 8 } }),
    );
    expect(screen.getByText("studio.liveDone")).toBeInTheDocument();
    expect(screen.queryByText("studio.liveWaiting")).not.toBeInTheDocument();

    // Parent re-renders with a NEW callback identity. On the buggy code the polling
    // effect tore down + re-ran, resetting status to "running" and re-firing onComplete.
    rerender(<Harness cb={cb} />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(cb).toHaveBeenCalledTimes(1);
    expect(screen.getByText("studio.liveDone")).toBeInTheDocument();
    expect(screen.queryByText("studio.liveWaiting")).not.toBeInTheDocument();
  });
});
