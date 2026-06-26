import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import type { SolutionExplanationState } from "@/hooks/useSolutionExplanation";

const { mockUseSolutionExplanation } = vi.hoisted(() => ({
  mockUseSolutionExplanation: vi.fn(),
}));

vi.mock("@/hooks/useSolutionExplanation", () => ({
  useSolutionExplanation: mockUseSolutionExplanation,
}));

vi.mock("@/lib/api", () => ({
  api: { request: vi.fn() },
}));

import { SolutionExplainer } from "../SolutionExplainer";

function makeStream(overrides: Partial<SolutionExplanationState> = {}): SolutionExplanationState {
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

describe("SolutionExplainer", () => {
  it("shows the unavailable message when the execution cannot be explained", () => {
    mockUseSolutionExplanation.mockReturnValue(makeStream());
    render(<SolutionExplainer executionId="exe_1" canExplain={false} />);
    expect(screen.getByText("solve.explainer.unavailable")).toBeInTheDocument();
  });

  it("renders the explain button when solved and idle", () => {
    mockUseSolutionExplanation.mockReturnValue(makeStream());
    render(<SolutionExplainer executionId="exe_1" canExplain={true} />);
    expect(screen.getByText("solve.explainer.button")).toBeInTheDocument();
    expect(screen.getByText("solve.explainer.title")).toBeInTheDocument();
  });

  it("shows the thinking indicator while streaming with no text yet", () => {
    mockUseSolutionExplanation.mockReturnValue(makeStream({ streaming: true, text: "" }));
    render(<SolutionExplainer executionId="exe_1" canExplain={true} />);
    expect(screen.getByText("solve.explainer.thinking")).toBeInTheDocument();
    // No button while streaming.
    expect(screen.queryByText("solve.explainer.button")).not.toBeInTheDocument();
  });

  it("renders streamed explanation text and the grounded footnote on completion", () => {
    mockUseSolutionExplanation.mockReturnValue(
      makeStream({ text: "Set x=1 and y=3 for objective 9.", streaming: false })
    );
    render(<SolutionExplainer executionId="exe_1" canExplain={true} />);
    expect(screen.getByText("Set x=1 and y=3 for objective 9.")).toBeInTheDocument();
    expect(screen.getByText("solve.explainer.grounded")).toBeInTheDocument();
  });

  it("renders a localized error (never a raw code) with the request ref", () => {
    mockUseSolutionExplanation.mockReturnValue(
      makeStream({ errorCode: "service_unavailable", requestId: "req_123" })
    );
    render(<SolutionExplainer executionId="exe_1" canExplain={true} />);
    expect(screen.getByText("builder.llm.error.serviceUnavailable")).toBeInTheDocument();
    // The mock i18n echoes the key (no message template), so the ref renders as its key.
    expect(screen.getByText("solve.explainer.ref")).toBeInTheDocument();
  });
});
