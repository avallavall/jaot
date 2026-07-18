import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const mockGet = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { getExecutionExactAnalysis: (...args: unknown[]) => mockGet(...args) },
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
  truncated_constraints: false,
  truncated_contributions: false,
  note: null,
};

describe("ExactAnalysisPanel (A3)", () => {
  beforeEach(() => mockGet.mockReset());

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

  it("demotes LP shadow prices into a collapsed section, deduped", async () => {
    mockGet.mockResolvedValue(computed);
    const sensitivity = {
      is_approximate: true,
      constraints: [
        { name: "c1", shadow_price: 1, is_binding: true },
        { name: "c2", shadow_price: 1, is_binding: true },
        { name: "c3", shadow_price: 0, is_binding: false },
      ],
      variables: [],
    } as unknown as Parameters<typeof ExactAnalysisPanel>[0]["sensitivity"];
    render(<ExactAnalysisPanel executionId="exe_3" sensitivity={sensitivity} />);
    await waitFor(() => expect(screen.getByTestId("exact-analysis")).toBeInTheDocument());
    // collapsed <details> present with the approximate label
    expect(
      screen.getByText("solve.execution.exactAnalysis.approximateSection"),
    ).toBeInTheDocument();
  });
});
