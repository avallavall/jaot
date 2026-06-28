import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import type { ModelExecution, OrganizationModel } from "@/lib/types";

// Capture the ExecutionProgress onComplete callback so a test can drive the
// async-completion flow directly with a chosen status payload.
const { onCompleteRef, mockApi } = vi.hoisted(() => ({
  onCompleteRef: { current: null as null | ((data: Record<string, unknown>) => void) },
  mockApi: {
    getMyModel: vi.fn(),
    getMyModelSchema: vi.fn(),
    previewModel: vi.fn(),
    validateProblem: vi.fn(),
    executeModelAsync: vi.fn(),
    getExecution: vi.fn(),
  },
}));

vi.mock("@/lib/api", () => ({
  api: mockApi,
  // Type-only re-exports the page imports as values under isolatedModules.
  OrganizationModel: {},
  ModelExecution: {},
  InputField: {},
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ modelId: "m1" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/hooks/useSolvers", () => ({
  useSolvers: () => ({
    solverName: "auto",
    setSolverName: vi.fn(),
    availableSolvers: [],
    solversLoading: false,
  }),
}));

// Heavy children replaced with markers so the test can assert which explainer
// the page chose and with what props.
vi.mock("@/components/ExecutionProgress", () => ({
  ExecutionProgress: (props: { onComplete?: (data: Record<string, unknown>) => void }) => {
    onCompleteRef.current = props.onComplete ?? null;
    return <div data-testid="execution-progress" />;
  },
}));

vi.mock("@/components/solve/SolutionExplainer", () => ({
  SolutionExplainer: ({ executionId, canExplain }: { executionId: string; canExplain: boolean }) => (
    <div
      data-testid="solution-explainer"
      data-execution-id={executionId}
      data-can-explain={String(canExplain)}
    />
  ),
}));

vi.mock("@/components/solve/InfeasibilityPanel", () => ({
  InfeasibilityPanel: ({ executionId }: { executionId: string }) => (
    <div data-testid="infeasibility-panel" data-execution-id={executionId} />
  ),
}));

vi.mock("@/components/solve/WarmStartDropdown", () => ({
  WarmStartDropdown: () => null,
}));

vi.mock("@/components/solve/SolverSelect", () => ({
  SolverSelect: () => null,
}));

import RunModelPage from "../page";

const model: OrganizationModel = {
  id: "m1",
  organization_id: "o1",
  catalog_id: "c1",
  display_name: "Telecom Model",
  description: "A test model",
  category: "telecommunications",
  is_active: true,
  is_favorite: false,
  total_executions: 0,
  total_credits_used: 0,
  credits_per_execution: 0,
  created_at: "2024-01-01T00:00:00Z",
} as unknown as OrganizationModel;

const schema = {
  input_fields: [],
  example_input: { requests: [{ name: "a", bandwidth: 1, value: 1 }] },
};

// The trimmed payload the async status endpoint delivers to onComplete: a `result`
// dict with NO `variables` and only a nested `solver_status`. This is exactly the
// shape that hid the explainer before the canonical-fetch fix.
const asyncStatusPayload = {
  status: "completed",
  execution_id: "exe_async_1",
  result: {
    model: { x: 1 },
    objective_value: 200,
    solver_status: "optimal",
    solve_time_seconds: 0.002,
  },
  credits_used: 8,
  execution_time_ms: 4,
};

async function loadAndRunAsync() {
  render(<RunModelPage />);
  await waitFor(() => expect(screen.getByRole("checkbox")).toBeInTheDocument());

  // Switch to async mode and start the run.
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.click(screen.getByRole("button", { name: /runModel/i }));

  // ExecutionProgress mounts once the async task id is set.
  await waitFor(() => expect(onCompleteRef.current).toBeTypeOf("function"));
}

describe("RunModelPage — async completion explainers", () => {
  beforeEach(() => {
    onCompleteRef.current = null;
    mockApi.getMyModel.mockResolvedValue(model);
    mockApi.getMyModelSchema.mockResolvedValue(schema);
    mockApi.previewModel.mockResolvedValue({});
    mockApi.validateProblem.mockResolvedValue({ estimated_credits: 8 });
    mockApi.executeModelAsync.mockResolvedValue({ task_id: "task_1" });
  });

  it("fetches the canonical execution so the solution explainer renders after an async solve", async () => {
    // The canonical record (what /executions/{id} returns) carries the full
    // shape: top-level solver_status + result_data.variables.
    mockApi.getExecution.mockResolvedValue({
      id: "exe_async_1",
      status: "completed",
      solver_status: "optimal",
      result_data: {
        model: { x: 1 },
        objective_value: 200,
        solver_status: "optimal",
        solve_time_seconds: 0.002,
        variables: [{ name: "x", value: 1 }],
      },
      credits_consumed: 8,
      execution_time_ms: 4,
    } as unknown as ModelExecution);

    await loadAndRunAsync();
    await act(async () => {
      await onCompleteRef.current!(asyncStatusPayload);
    });

    // The page must hydrate from the canonical execution, not the trimmed payload.
    expect(mockApi.getExecution).toHaveBeenCalledWith("exe_async_1");

    const explainer = await screen.findByTestId("solution-explainer");
    expect(explainer).toBeInTheDocument();
    // Real execution id (exe_), never the Celery task_id.
    expect(explainer).toHaveAttribute("data-execution-id", "exe_async_1");
    expect(explainer).toHaveAttribute("data-can-explain", "true");
  });

  it("renders the infeasibility panel (not the solution explainer) for an infeasible async solve", async () => {
    mockApi.getExecution.mockResolvedValue({
      id: "exe_async_2",
      status: "completed",
      solver_status: "infeasible",
      result_data: {
        model: {},
        solver_status: "infeasible",
        variables: [],
      },
      credits_consumed: 8,
      execution_time_ms: 4,
    } as unknown as ModelExecution);

    await loadAndRunAsync();
    await act(async () => {
      await onCompleteRef.current!({ ...asyncStatusPayload, execution_id: "exe_async_2" });
    });

    expect(await screen.findByTestId("infeasibility-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("solution-explainer")).not.toBeInTheDocument();
  });
});
