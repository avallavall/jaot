import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const mockGet = vi.fn();
// Deliberately NOT stubbed: this panel must not reach for the what-if job or the
// LP duals any more — both belong to the Sensitivity tab. A call would throw here.
vi.mock("@/lib/api", () => ({
  api: {
    getExecutionExactAnalysis: (...args: unknown[]) => mockGet(...args),
  },
}));

import { ExactAnalysisPanel } from "../ExactAnalysisPanel";
import type { ExactAnalysis } from "@/lib/types";

const computed: ExactAnalysis = {
  computed: true,
  objective_value: 22,
  total_constraints: 2,
  binding_count: 1,
  constraints: [
    { name: "cap", activity: 10, rhs: 10, operator: "<=", slack: 0, is_binding: true, utilization: 1 },
    { name: "room", activity: 10, rhs: 20, operator: "<=", slack: 10, is_binding: false, utilization: 0.5 },
  ],
  contributions: [
    { label: "y", contribution: 16 },
    { label: "x", contribution: 6 },
  ],
  families: [],
  contribution_families: [],
  truncated_constraints: false,
  truncated_contributions: false,
  truncated_families: false,
  note: null,
};

const withFamilies: ExactAnalysis = {
  ...computed,
  families: [
    {
      family: "cap",
      total: 4,
      binding_count: 1,
      slack_min: 0,
      slack_mean: 5,
      slack_max: 10,
      utilization_mean: 0.75,
      utilization_max: 1,
    },
    {
      family: "floor",
      total: 3,
      binding_count: 0,
      slack_min: 1,
      slack_mean: 2,
      slack_max: 3,
      utilization_mean: null,
      utilization_max: null,
    },
  ],
  contribution_families: [
    { family: "y", contribution: 16, terms: 1 },
    { family: "x", contribution: 6, terms: 2 },
  ],
};

describe("ExactAnalysisPanel (A3)", () => {
  beforeEach(() => {
    mockGet.mockReset();
  });

  it("leads with binding constraints + objective contributions once loaded", async () => {
    mockGet.mockResolvedValue(computed);
    render(<ExactAnalysisPanel executionId="exe_1" />);
    await waitFor(() => expect(screen.getByTestId("exact-analysis")).toBeInTheDocument());
    // the binding constraint is listed, the non-binding "room" appears in the table
    expect(screen.getAllByText("cap").length).toBeGreaterThan(0);
    expect(screen.getByText("y")).toBeInTheDocument(); // top objective contribution
    expect(mockGet).toHaveBeenCalledWith("exe_1");
  });

  it("shows a graceful message when there is no solution to analyze", async () => {
    mockGet.mockResolvedValue({ ...computed, computed: false, note: "no_solution" });
    render(<ExactAnalysisPanel executionId="exe_2" />);
    await waitFor(() =>
      expect(
        screen.getByText("solve.execution.exactAnalysis.noSolution"),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("exact-analysis")).not.toBeInTheDocument();
  });

  it("shows family KPIs when the analysis recovered constraint families", async () => {
    mockGet.mockResolvedValue(withFamilies);
    render(<ExactAnalysisPanel executionId="exe_4" />);
    await waitFor(() => expect(screen.getByTestId("exact-analysis-families")).toBeInTheDocument());
    // saturation ratio + slack spread of the "cap" family
    expect(screen.getByText("1/4")).toBeInTheDocument();
    expect(screen.getByText("(25%)")).toBeInTheDocument();
    expect(screen.getByText("0 / 5 / 10")).toBeInTheDocument();
    expect(screen.getByText("75% · 100%")).toBeInTheDocument();
    // a >=-only family has no utilization — em dash, not a bogus 0%
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    // family contribution bars render one row per family
    expect(
      screen.getByText("solve.execution.exactAnalysis.familyContributions"),
    ).toBeInTheDocument();
  });

  it("hides the family sections when no structure was recovered", async () => {
    mockGet.mockResolvedValue(computed);
    render(<ExactAnalysisPanel executionId="exe_5" />);
    await waitFor(() => expect(screen.getByTestId("exact-analysis")).toBeInTheDocument());
    expect(screen.queryByTestId("exact-analysis-families")).not.toBeInTheDocument();
    expect(
      screen.queryByText("solve.execution.exactAnalysis.familyContributions"),
    ).not.toBeInTheDocument();
  });

  it("survives a stale backend that omits the family fields", async () => {
    const legacy = { ...computed } as Record<string, unknown>;
    delete legacy.families;
    delete legacy.contribution_families;
    delete legacy.truncated_families;
    mockGet.mockResolvedValue(legacy);
    render(<ExactAnalysisPanel executionId="exe_6" />);
    await waitFor(() => expect(screen.getByTestId("exact-analysis")).toBeInTheDocument());
    expect(screen.queryByTestId("exact-analysis-families")).not.toBeInTheDocument();
  });

  // CONTRACT-TEST: the exact analysis answers "how did my solution come out?" only.
  // Shadow prices used to render here AND in the Sensitivity tab AND inside the
  // solution explorer — the same numbers three times on one page — while the
  // what-if sat at the bottom of a tab named Results. Both now live in the
  // Sensitivity tab, and nothing here may bring them back.
  it("shows no shadow prices and no what-if — those belong to the Sensitivity tab", async () => {
    mockGet.mockResolvedValue(computed);
    render(<ExactAnalysisPanel executionId="exe_3" />);
    await waitFor(() => expect(screen.getByTestId("exact-analysis")).toBeInTheDocument());
    for (const key of [
      "solve.execution.exactAnalysis.approximateSection",
      "solve.execution.exactAnalysis.exactDualsSection",
      "solve.execution.exactAnalysis.shadowPriceGroup",
      "solve.execution.scenarioAnalysis.title",
    ]) {
      expect(screen.queryByText(key)).not.toBeInTheDocument();
    }
  });
});
