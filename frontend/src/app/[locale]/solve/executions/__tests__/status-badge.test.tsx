/**
 * "Completed" is the job's state, and it is not painted as a success when the
 * solver found no plan.
 *
 * An infeasible run's page showed a green "Completed" badge next to "Solver
 * Status: Infeasible" (browser QA, 2026-09-24). The job did complete: the
 * solver ran to the end. The colour said the run had worked.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

const { getExecution, getAllExecutions } = vi.hoisted(() => ({
  getExecution: vi.fn(),
  getAllExecutions: vi.fn(),
}));

vi.mock("next-intl", () => ({
  useTranslations: (ns: string) => {
    const t = (key: string, values?: Record<string, unknown>) =>
      `${ns}.${key}${values ? ` ${JSON.stringify(values)}` : ""}`;
    return Object.assign(t, { rich: t, has: () => true });
  },
  useLocale: () => "en",
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ executionId: "exe_1" }),
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
}));

vi.mock("@/i18n/navigation", () => ({
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/lib/api", () => ({
  api: { getExecution, getAllExecutions },
  ApiError: class ApiError extends Error {},
}));

vi.mock("@/hooks/useSolvers", () => ({ useSolverCapabilities: () => undefined }));
vi.mock("@/components/solve/ExportButtons", () => ({ ExportButtons: () => null }));
vi.mock("@/components/solve/InfeasibilityPanel", () => ({ InfeasibilityPanel: () => null }));

import ExecutionDetailPage from "../[executionId]/page";
import ExecutionsPage from "../page";

const COMPLETED = "common.executionStatus.completed";

function run(solverStatus: string, objective: number | null) {
  return {
    id: "exe_1",
    organization_model_id: null,
    status: "completed",
    solver_status: solverStatus,
    solver_name: "jaos",
    objective_value: objective,
    execution_time_ms: 40,
    origin: "manual",
    created_at: "2026-09-24T10:00:00Z",
    input_data: { name: "p" },
    result_data: {
      objective_value: objective,
      solver_status: solverStatus,
      solver_used: "jaos",
      variables: [],
    },
  };
}

async function detailBadge(solverStatus: string, objective: number | null) {
  getExecution.mockResolvedValue(run(solverStatus, objective));
  render(<ExecutionDetailPage />);
  return screen.findByTestId("execution-status-badge");
}

describe("the job-state badge on a run's page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it.each([
    ["infeasible", null],
    ["unbounded", null],
    ["time_limit", null],
  ])("is neutral, not green, when the run ended %s with no plan", async (status, objective) => {
    const badge = await detailBadge(status, objective);
    expect(badge.textContent).toBe(COMPLETED);
    expect(badge.className).not.toMatch(/green/);
  });

  it.each([
    ["optimal", 485],
    ["feasible", 450],
    ["time_limit", 450],
  ])("stays green when the run ended %s with a plan", async (status, objective) => {
    const badge = await detailBadge(status, objective);
    expect(badge.textContent).toBe(COMPLETED);
    expect(badge.className).toMatch(/green/);
  });
});

describe("the job-state badge in the run history", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("is neutral for an infeasible run and green for an optimal one", async () => {
    getAllExecutions.mockResolvedValue({
      items: [
        { ...run("infeasible", null), id: "exe_inf", result_data: undefined },
        { ...run("optimal", 485), id: "exe_opt", result_data: undefined },
      ],
      total: 2,
    });

    render(<ExecutionsPage />);

    const [infeasible, optimal] = await screen.findAllByTestId("execution-status-badge");
    expect(infeasible.textContent).toBe(COMPLETED);
    expect(infeasible.className).not.toMatch(/green/);
    expect(optimal.className).toMatch(/green/);
  });
});
