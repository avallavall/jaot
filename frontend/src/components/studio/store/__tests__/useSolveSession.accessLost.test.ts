import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

/**
 * The reconcile poll is the signal that arrives when the user is only looking.
 *
 * It asks for this model's latest run every seven seconds. A 403 there means
 * somebody took the caller out of the model's workspace while the page was
 * open — the same answer the autosave gets, but this one needs no typing. It
 * used to be swallowed as `catch { /* best-effort *\/ }`, so the poll asked
 * again forever and the editor stayed on screen saying nothing. Driving the app
 * counted six refusals before the sweep gave up (QA, 2026-08-20).
 */

vi.mock("@/lib/api", () => ({
  api: { getProjectExecutions: vi.fn(), getAsyncSolveStatus: vi.fn() },
}));

vi.mock("@/hooks/useExecutionWebSocket", () => ({
  useExecutionWebSocket: () => undefined,
}));

import { useSolveSession } from "../useSolveSession";
import { createModelProjectStore } from "../createModelProjectStore";
import { api } from "@/lib/api";
import type { OptimizationProblem } from "@/lib/types";

const getExecutions = api.getProjectExecutions as unknown as ReturnType<typeof vi.fn>;

const EMPTY: OptimizationProblem = {
  variables: [],
  objective: { sense: "minimize", expression: "0" },
  constraints: [],
};

const POLL_MS = 7000;

function denied() {
  return Object.assign(new Error("You are not a member of this workspace"), { status: 403 });
}

async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("the reconcile poll when the workspace is taken away", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("raises accessLost on a 403 and stops asking", async () => {
    const store = createModelProjectStore({ modelId: "mp_1", name: "M", problem: EMPTY });
    getExecutions.mockRejectedValue(denied());

    renderHook(() => useSolveSession(store));
    await settle();

    expect(getExecutions).toHaveBeenCalledTimes(1);
    expect(store.getState().accessLost).toBe(true);

    // Three poll windows. The old code sent one refused request per window for
    // as long as the tab stayed open.
    await act(async () => {
      vi.advanceTimersByTime(POLL_MS * 3);
      await Promise.resolve();
    });

    expect(getExecutions).toHaveBeenCalledTimes(1);
  });

  it("keeps polling through an ordinary failure", async () => {
    const store = createModelProjectStore({ modelId: "mp_2", name: "M", problem: EMPTY });
    getExecutions.mockRejectedValue(Object.assign(new Error("gateway"), { status: 502 }));

    renderHook(() => useSolveSession(store));
    await settle();
    expect(getExecutions).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(POLL_MS);
      await Promise.resolve();
    });
    await settle();

    expect(getExecutions).toHaveBeenCalledTimes(2);
    expect(store.getState().accessLost).toBe(false);
  });
});
