import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// The i18n-aware Link renders a plain anchor in tests.
vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { SolveResultsDrawer } from "../SolveResultsDrawer";
import type { SolveResult } from "@/lib/types";

const result = {
  status: "optimal",
  objective_value: 17,
  solve_time_seconds: 0.4,
  variables: [
    { name: "a_1", value: 1, type: "binary" },
    { name: "a_2", value: 0, type: "binary" },
  ],
} as unknown as SolveResult;

describe("SolveResultsDrawer — A5 studio slim view vs full view", () => {
  it("links to the full execution page (no crammed table) when executionId is set", () => {
    render(
      <SolveResultsDrawer result={result} isOpen onClose={() => {}} executionId="exe_abc123" />,
    );
    const cta = screen.getByTestId("drawer-view-full-results");
    expect(cta).toBeInTheDocument();
    expect(cta.getAttribute("href")).toContain("/solve/executions/exe_abc123");
    // the heavy full variable table + its non-zero toggle are NOT crammed in here
    expect(screen.queryByTestId("drawer-nonzero-toggle")).not.toBeInTheDocument();
  });

  it("keeps the full inline table when no executionId is provided (builder / template)", () => {
    render(<SolveResultsDrawer result={result} isOpen onClose={() => {}} />);
    expect(screen.queryByTestId("drawer-view-full-results")).not.toBeInTheDocument();
    expect(screen.getByTestId("drawer-nonzero-toggle")).toBeInTheDocument();
  });
});

describe("SolveResultsDrawer — a run stopped by its time limit", () => {
  const stopped = {
    status: "time_limit",
    objective_value: 450,
    solve_time_seconds: 60.1,
    variables: [{ name: "a_1", value: 1, type: "binary" }],
  } as unknown as SolveResult;

  // The explanation says "the result shown is the best solution found so far",
  // and the drawer then showed no objective and no link to it.
  it("shows the plan it holds, labelled as the best value found", () => {
    render(<SolveResultsDrawer result={stopped} isOpen onClose={() => {}} executionId="exe_tl" />);
    expect(screen.getByText("builder.results.bestValueFound")).toBeInTheDocument();
    expect(screen.getByText("450.0000")).toBeInTheDocument();
    expect(screen.getByTestId("drawer-view-full-results")).toBeInTheDocument();
  });

  it("shows nothing to act on when the time limit came before any plan", () => {
    const empty = { ...stopped, objective_value: null, variables: [] } as unknown as SolveResult;
    render(<SolveResultsDrawer result={empty} isOpen onClose={() => {}} executionId="exe_tl" />);
    expect(screen.queryByText("builder.results.bestValueFound")).not.toBeInTheDocument();
    expect(screen.queryByTestId("drawer-view-full-results")).not.toBeInTheDocument();
  });
});
