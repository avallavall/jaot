import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import type { InfeasibilityExplanationState } from "@/hooks/useInfeasibilityExplanation";
import type { InfeasibilityAnalysis } from "@/lib/llm-types";

const { mockUseInfeasibilityExplanation } = vi.hoisted(() => ({
  mockUseInfeasibilityExplanation: vi.fn(),
}));

vi.mock("@/hooks/useInfeasibilityExplanation", () => ({
  useInfeasibilityExplanation: mockUseInfeasibilityExplanation,
}));

vi.mock("@/lib/api", () => ({
  api: { request: vi.fn(), analyzeInfeasibility: vi.fn() },
}));

import { InfeasibilityPanel } from "../InfeasibilityPanel";

function makeStream(
  overrides: Partial<InfeasibilityExplanationState> = {}
): InfeasibilityExplanationState {
  return {
    text: "",
    streaming: false,
    statusCode: null,
    errorCode: null,
    requestId: null,
    explain: vi.fn(),
    stop: vi.fn(),
    ...overrides,
  };
}

const IIS_ANALYSIS: InfeasibilityAnalysis = {
  iis_constraints: ["floor", "ceiling"],
  iis_variable_bounds: [],
  conflict_type: "constraint",
  method: "iis",
  note: null,
  explanation: null,
};

describe("InfeasibilityPanel", () => {
  it("renders the explain button and title when idle", () => {
    mockUseInfeasibilityExplanation.mockReturnValue(makeStream());
    render(<InfeasibilityPanel executionId="exe_1" />);
    expect(screen.getByText("solve.infeasibility.button")).toBeInTheDocument();
    expect(screen.getByText("solve.infeasibility.title")).toBeInTheDocument();
  });

  it("shows the conflicting constraints when an IIS is available", () => {
    mockUseInfeasibilityExplanation.mockReturnValue(makeStream());
    render(<InfeasibilityPanel executionId="exe_1" initialAnalysis={IIS_ANALYSIS} />);
    expect(screen.getByText("solve.infeasibility.conflictHeading")).toBeInTheDocument();
    expect(screen.getByText("floor")).toBeInTheDocument();
    expect(screen.getByText("ceiling")).toBeInTheDocument();
  });

  it("shows the heuristic badge when the exact set was not computed", () => {
    mockUseInfeasibilityExplanation.mockReturnValue(makeStream());
    render(
      <InfeasibilityPanel
        executionId="exe_1"
        initialAnalysis={{
          ...IIS_ANALYSIS,
          iis_constraints: [],
          conflict_type: "unknown",
          method: "llm_only",
          note: "model too large for exact IIS",
        }}
      />
    );
    expect(screen.getByText("solve.infeasibility.heuristic")).toBeInTheDocument();
    expect(screen.getByText("solve.infeasibility.heuristicHint")).toBeInTheDocument();
  });

  it("shows the thinking indicator while streaming with no text yet", () => {
    mockUseInfeasibilityExplanation.mockReturnValue(makeStream({ streaming: true, text: "" }));
    render(<InfeasibilityPanel executionId="exe_1" />);
    expect(screen.getByText("solve.infeasibility.thinking")).toBeInTheDocument();
    expect(screen.queryByText("solve.infeasibility.button")).not.toBeInTheDocument();
  });

  it("renders streamed explanation text and the grounded footnote on completion", () => {
    mockUseInfeasibilityExplanation.mockReturnValue(
      makeStream({ text: "Constraints floor and ceiling conflict; relax one.", streaming: false })
    );
    render(<InfeasibilityPanel executionId="exe_1" />);
    expect(
      screen.getByText("Constraints floor and ceiling conflict; relax one.")
    ).toBeInTheDocument();
    expect(screen.getByText("solve.infeasibility.grounded")).toBeInTheDocument();
  });

  it("renders a localized error (never a raw code) with the request ref", () => {
    mockUseInfeasibilityExplanation.mockReturnValue(
      makeStream({ errorCode: "service_unavailable", requestId: "req_123" })
    );
    render(<InfeasibilityPanel executionId="exe_1" />);
    expect(screen.getByText("builder.llm.error.serviceUnavailable")).toBeInTheDocument();
    expect(screen.getByText("solve.infeasibility.ref")).toBeInTheDocument();
  });
});
