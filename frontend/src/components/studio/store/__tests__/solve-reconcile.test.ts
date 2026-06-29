import { describe, it, expect } from "vitest";
import { createModelProjectStore } from "../createModelProjectStore";
import { applyReconciledExecution } from "../useSolveSession";
import type { OptimizationProblem, ProjectExecutionItem } from "@/lib/types";

const EMPTY: OptimizationProblem = {
  variables: [],
  objective: { sense: "minimize", expression: "0" },
  constraints: [],
};

function exec(over: Partial<ProjectExecutionItem>): ProjectExecutionItem {
  return {
    id: "exe_1",
    status: "running",
    is_async: true,
    created_at: "2026-06-29T10:00:00Z",
    ...over,
  };
}

describe("applyReconciledExecution — server-derived solve reconciliation (§14)", () => {
  it("re-attaches a still-running async solve by its celery task id", () => {
    const store = createModelProjectStore({ modelId: "mp_1", name: "M", problem: EMPTY });
    applyReconciledExecution(
      store,
      exec({
        status: "running",
        is_async: true,
        celery_task_id: "celery-123",
        solver_name: "scip",
        started_at: "2026-06-29T07:00:00Z",
      })
    );
    expect(store.getState().solveSession).toMatchObject({
      taskId: "celery-123",
      status: "running",
      solverName: "scip",
      // The server's real start time (not "now") keeps "started Xm ago" honest.
      startedAt: "2026-06-29T07:00:00Z",
    });
    // A re-attach must NOT also leave a stale "last run" banner showing.
    expect(store.getState().lastRun).toBeNull();
  });

  it("falls back to created_at for the start time when started_at is absent", () => {
    const store = createModelProjectStore({ modelId: "mp_1", name: "M", problem: EMPTY });
    applyReconciledExecution(
      store,
      exec({ status: "running", celery_task_id: "c", created_at: "2026-06-29T06:00:00Z" })
    );
    expect(store.getState().solveSession.startedAt).toBe("2026-06-29T06:00:00Z");
  });

  it("re-attaches a 'pending' run too (the row exists before the worker picks it up)", () => {
    const store = createModelProjectStore({ modelId: "mp_1", name: "M", problem: EMPTY });
    applyReconciledExecution(store, exec({ status: "pending", celery_task_id: "celery-p" }));
    expect(store.getState().solveSession.status).toBe("running");
    expect(store.getState().solveSession.taskId).toBe("celery-p");
  });

  it("does NOT re-attach a running row that has no celery task id (un-attachable)", () => {
    const store = createModelProjectStore({ modelId: "mp_1", name: "M", problem: EMPTY });
    applyReconciledExecution(store, exec({ status: "running", celery_task_id: null }));
    expect(store.getState().solveSession.status).toBe("idle");
    expect(store.getState().lastRun).toBeNull();
  });

  it("surfaces a finished solve as the 'last run' with its objective", () => {
    const store = createModelProjectStore({ modelId: "mp_1", name: "M", problem: EMPTY });
    applyReconciledExecution(
      store,
      exec({
        id: "exe_done",
        status: "completed",
        is_async: true,
        objective_value: 90,
        solver_name: "highs",
        completed_at: "2026-06-29T09:00:00Z",
      })
    );
    expect(store.getState().solveSession.status).toBe("idle"); // no live session
    expect(store.getState().lastRun).toEqual({
      executionId: "exe_done",
      status: "completed",
      objectiveValue: 90,
      solverName: "highs",
      finishedAt: "2026-06-29T09:00:00Z",
    });
  });

  it("maps a failed run to a last-run with a null objective", () => {
    const store = createModelProjectStore({ modelId: "mp_1", name: "M", problem: EMPTY });
    applyReconciledExecution(store, exec({ status: "failed", is_async: true }));
    expect(store.getState().lastRun).toMatchObject({ status: "failed", objectiveValue: null });
  });

  it("falls back to created_at when a finished run has no completed_at", () => {
    const store = createModelProjectStore({ modelId: "mp_1", name: "M", problem: EMPTY });
    applyReconciledExecution(
      store,
      exec({ status: "cancelled", completed_at: null, created_at: "2026-06-29T08:00:00Z" })
    );
    expect(store.getState().lastRun?.finishedAt).toBe("2026-06-29T08:00:00Z");
  });

  it("is a no-op when there is no execution", () => {
    const store = createModelProjectStore({ modelId: "mp_1", name: "M", problem: EMPTY });
    applyReconciledExecution(store, undefined);
    expect(store.getState().solveSession.status).toBe("idle");
    expect(store.getState().lastRun).toBeNull();
  });

  it("never clobbers a solve the user already started in this session", () => {
    const store = createModelProjectStore({ modelId: "mp_1", name: "M", problem: EMPTY });
    store.getState().startSolveSession("user-task", "scip");
    // A late server reconcile must not overwrite the in-flight session.
    applyReconciledExecution(store, exec({ status: "running", celery_task_id: "other-task" }));
    expect(store.getState().solveSession.taskId).toBe("user-task");
    expect(store.getState().lastRun).toBeNull();
  });
});
