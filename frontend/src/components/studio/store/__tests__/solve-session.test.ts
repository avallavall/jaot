import { describe, it, expect } from "vitest";
import { createModelProjectStore } from "../createModelProjectStore";
import type { OptimizationProblem } from "@/lib/types";

const EMPTY: OptimizationProblem = {
  variables: [],
  objective: { sense: "minimize", expression: "0" },
  constraints: [],
};

describe("solveSession survives tab switches", () => {
  it("the session lives in the store (not the panel) so it persists across a panel unmount/remount", () => {
    const store = createModelProjectStore({ modelId: "mp_1", name: "M", problem: EMPTY });
    expect(store.getState().solveSession.status).toBe("idle");

    // SolvePanel.handleSolve → startSolveSession after solveAsync returns a task id.
    store.getState().startSolveSession("task_x", "scip");
    expect(store.getState().solveSession).toMatchObject({
      taskId: "task_x",
      status: "running",
      solverName: "scip",
    });

    // Switch to Construir/Analizar → SolvePanel unmounts. The store is owned by the
    // provider, so the running session is untouched. (On the old code the session was
    // SolvePanel-local useState and would be GONE here — the bug the owner hit.)
    expect(store.getState().solveSession.status).toBe("running");
    expect(store.getState().solveSession.taskId).toBe("task_x");

    // The provider-level poller finishes the solve while we're on another tab.
    const result = { status: "optimal", objective_value: 8 } as never;
    store.getState().finishSolveSession(result, []);

    // Back on the Solve tab → the store still holds the finished result.
    expect(store.getState().solveSession.status).toBe("done");
    expect(store.getState().solveSession.result).toBe(result);
  });

  it("addSolvePoint only accumulates while running; clear resets to idle", () => {
    const store = createModelProjectStore({ modelId: "mp_2", name: "M", problem: EMPTY });
    store.getState().startSolveSession("t", "scip");
    const pt = { iteration: 1, objective: 5, gap: 0.1, timestamp: 100 };
    store.getState().addSolvePoint(pt, { objective: 5 });
    expect(store.getState().solveSession.points).toHaveLength(1);

    store.getState().clearSolveSession();
    expect(store.getState().solveSession.status).toBe("idle");
    store.getState().addSolvePoint(pt, { objective: 5 }); // idle → no-op
    expect(store.getState().solveSession.points).toHaveLength(0);
  });
});
