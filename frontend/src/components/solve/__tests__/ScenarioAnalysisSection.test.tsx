import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const mockGet = vi.fn();
const mockStart = vi.fn();
const mockExplain = vi.fn();
vi.mock("@/lib/api", () => ({
  api: {
    getExecutionScenarioAnalysis: (...args: unknown[]) => mockGet(...args),
    startExecutionScenarioAnalysis: (...args: unknown[]) => mockStart(...args),
    explainExecutionScenarios: (...args: unknown[]) => mockExplain(...args),
  },
}));

import { ScenarioAnalysisSection } from "../ScenarioAnalysisSection";
import type { ScenarioAnalysisJob } from "@/lib/types";

function job(overrides: Partial<ScenarioAnalysisJob> = {}): ScenarioAnalysisJob {
  return {
    status: "absent",
    analysis: null,
    error: null,
    requested_at: null,
    completed_at: null,
    ...overrides,
  } as ScenarioAnalysisJob;
}

const completed = job({
  status: "completed",
  analysis: {
    computed: true,
    note: null,
    sense: "maximize",
    base_objective: 24,
    rhs_scenarios: [
      {
        constraint: "cap",
        family: null,
        operator: "<=",
        direction: "relax",
        is_equality: false,
        rhs: 10,
        rhs_new: 11,
        delta: 1,
        status: "computed",
        objective_value: 26,
        objective_delta: 2,
        objective_delta_per_unit: 2,
        improves: true,
        solve_time_seconds: 0.1,
      },
      {
        constraint: "xmax",
        family: null,
        operator: "<=",
        direction: "tighten",
        is_equality: false,
        rhs: 4,
        rhs_new: 3,
        delta: 1,
        status: "computed",
        objective_value: 23,
        objective_delta: -1,
        objective_delta_per_unit: -1,
        improves: false,
        solve_time_seconds: 0.1,
      },
    ],
    decision_scenarios: [
      {
        variable: "open_a",
        family: null,
        original_value: 1,
        forced_value: 0,
        status: "computed",
        objective_value: 9,
        regret: 15,
        solve_time_seconds: 0.2,
      },
    ],
    resolves_used: 3,
    resolves_planned: 3,
    seconds_used: 1.2,
    budget_seconds: 300,
    per_solve_limit_seconds: 30,
    partial: false,
  },
});

describe("ScenarioAnalysisSection (Sensitivity L2)", () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockStart.mockReset();
    mockExplain.mockReset();
  });

  it("offers the batch when it has never been run", async () => {
    mockGet.mockResolvedValue(job());
    render(<ScenarioAnalysisSection executionId="exe_1" />);

    await waitFor(() =>
      expect(screen.getByTestId("scenario-analysis-start")).toBeInTheDocument(),
    );
    expect(mockGet).toHaveBeenCalledWith("exe_1");
    expect(screen.queryByTestId("scenario-tornado")).not.toBeInTheDocument();
  });

  it("starts the batch on demand and then reports it running", async () => {
    mockGet.mockResolvedValue(job());
    mockStart.mockResolvedValue(job({ status: "running" }));
    render(<ScenarioAnalysisSection executionId="exe_2" />);

    await waitFor(() =>
      expect(screen.getByTestId("scenario-analysis-start")).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByTestId("scenario-analysis-start"));

    await waitFor(() =>
      expect(screen.getByTestId("scenario-analysis-running")).toBeInTheDocument(),
    );
    expect(mockStart).toHaveBeenCalledWith("exe_2");
    // The button is gone while the batch runs — no second batch from a double click.
    expect(screen.queryByTestId("scenario-analysis-start")).not.toBeInTheDocument();
  });

  it("charts the measured deltas, biggest first, and prices the regret", async () => {
    mockGet.mockResolvedValue(completed);
    render(<ScenarioAnalysisSection executionId="exe_3" />);

    await waitFor(() => expect(screen.getByTestId("scenario-tornado")).toBeInTheDocument());
    const rows = screen.getByTestId("scenario-tornado").querySelectorAll(".font-mono");
    // |2| ranks above |−1|
    expect(rows[0].textContent).toContain("cap");
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("-1")).toBeInTheDocument();
    // regret table carries the cost of overruling the decision
    expect(screen.getByTestId("scenario-regret")).toBeInTheDocument();
    expect(screen.getByText("open_a")).toBeInTheDocument();
    expect(screen.getByText("15")).toBeInTheDocument();
  });

  it("says so when the budget ran out instead of implying a full sweep", async () => {
    mockGet.mockResolvedValue(
      job({
        status: "completed",
        analysis: {
          ...completed.analysis!,
          resolves_used: 4,
          resolves_planned: 20,
          partial: true,
        },
      }),
    );
    render(<ScenarioAnalysisSection executionId="exe_4" />);

    await waitFor(() => expect(screen.getByTestId("scenario-partial")).toBeInTheDocument());
  });

  it("marks a time-limited scenario as a bound, not an exact value", async () => {
    mockGet.mockResolvedValue(
      job({
        status: "completed",
        analysis: {
          ...completed.analysis!,
          rhs_scenarios: [
            { ...completed.analysis!.rhs_scenarios[0], status: "time_limit" },
          ],
          decision_scenarios: [],
        },
      }),
    );
    render(<ScenarioAnalysisSection executionId="exe_5" />);

    await waitFor(() => expect(screen.getByTestId("scenario-tornado")).toBeInTheDocument());
    expect(screen.getByTitle("solve.execution.scenarioAnalysis.statusTimeLimit")).toBeInTheDocument();
  });

  it("reports an infeasible scenario as a finding, not a blank row", async () => {
    mockGet.mockResolvedValue(
      job({
        status: "completed",
        analysis: {
          ...completed.analysis!,
          rhs_scenarios: [
            {
              ...completed.analysis!.rhs_scenarios[0],
              status: "infeasible",
              objective_value: null,
              objective_delta: null,
              objective_delta_per_unit: null,
              improves: null,
            },
          ],
          decision_scenarios: [],
        },
      }),
    );
    render(<ScenarioAnalysisSection executionId="exe_6" />);

    await waitFor(() => expect(screen.getByTestId("scenario-tornado")).toBeInTheDocument());
    expect(
      screen.getByText("solve.execution.scenarioAnalysis.statusInfeasible"),
    ).toBeInTheDocument();
  });

  it("explains the analysis in plain language on demand", async () => {
    mockGet.mockResolvedValue(completed);
    mockExplain.mockResolvedValue({
      explanation: "Demand is what limits you.",
      cached: false,
    });
    render(<ScenarioAnalysisSection executionId="exe_8" />);

    await waitFor(() => expect(screen.getByTestId("scenario-explain-button")).toBeInTheDocument());
    await userEvent.click(screen.getByTestId("scenario-explain-button"));

    await waitFor(() =>
      expect(screen.getByTestId("scenario-explanation-text")).toBeInTheDocument(),
    );
    expect(screen.getByText("Demand is what limits you.")).toBeInTheDocument();
    expect(mockExplain).toHaveBeenCalledWith("exe_8", false);
  });

  it("shows an already-written explanation without asking for another", async () => {
    mockGet.mockResolvedValue({
      ...completed,
      explanation: "Capacity on machine 3 is your real limit.",
    });
    render(<ScenarioAnalysisSection executionId="exe_9" />);

    await waitFor(() =>
      expect(screen.getByTestId("scenario-explanation-text")).toBeInTheDocument(),
    );
    // Cached server-side: no button, and no model call from the page load.
    expect(screen.queryByTestId("scenario-explain-button")).not.toBeInTheDocument();
    expect(mockExplain).not.toHaveBeenCalled();
  });

  it("declines gracefully when there is nothing to vary", async () => {
    mockGet.mockResolvedValue(
      job({
        status: "completed",
        analysis: { ...completed.analysis!, computed: false, note: "no_scenarios" },
      }),
    );
    render(<ScenarioAnalysisSection executionId="exe_7" />);

    await waitFor(() =>
      expect(
        screen.getByText("solve.execution.scenarioAnalysis.noScenarios"),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("scenario-tornado")).not.toBeInTheDocument();
  });
});
