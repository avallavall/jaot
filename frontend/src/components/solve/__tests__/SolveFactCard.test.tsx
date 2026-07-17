import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SolveFactCard } from "../SolveFactCard";

// next-intl is globally mocked in src/test/setup.tsx to render "<namespace>.<key>",
// so we assert on the key the honest headline resolves to (+ real metric values).
const NS = "solve.execution.summary";

describe("SolveFactCard — honest post-solve headline (A2)", () => {
  it("says 'root node' when an optimal solve did not branch", () => {
    render(<SolveFactCard status="optimal" nodes={1} objectiveValue={17} solveTimeSeconds={0.4} />);
    expect(screen.getByTestId("solve-fact-card")).toBeInTheDocument();
    expect(screen.getByText(`${NS}.headlineRootNode`)).toBeInTheDocument();
  });

  it("reports branched (with the node count metric) when the model branched", () => {
    render(
      <SolveFactCard status="optimal" nodes={1936} objectiveValue={6624} solveTimeSeconds={3.2} />,
    );
    expect(screen.getByText(`${NS}.headlineBranched`)).toBeInTheDocument();
    // Node's thousands separator varies by ICU build; match with or without it.
    expect(screen.getByText(/1[,.\s]?936/)).toBeInTheDocument();
  });

  it("shows the gap metric for a time-limited solve", () => {
    render(<SolveFactCard status="time_limit" gap={0.05} objectiveValue={100} />);
    expect(screen.getByText(`${NS}.headlineTimeLimit`)).toBeInTheDocument();
    expect(screen.getByText("5.00%")).toBeInTheDocument();
  });

  it("degrades to plain 'optimal proven' when node telemetry is absent (old rows)", () => {
    render(<SolveFactCard status="optimal" objectiveValue={42} />);
    expect(screen.getByText(`${NS}.headlineOptimal`)).toBeInTheDocument();
  });
});
