/**
 * SolutionGraphView — draws the graph, and knows when there is none to draw.
 *
 * The load-bearing behaviour is the refusal: a model with no edge-shaped family
 * must produce NOTHING, not an empty frame with a heading over it. next-intl is
 * mocked suite-wide to echo `namespace.key`, so assertions target keys.
 */
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

const getExecutionSolutionGraph = vi.fn();
vi.mock("@/lib/api", () => ({
  api: {
    getExecutionSolutionGraph: (...args: unknown[]) => getExecutionSolutionGraph(...args),
  },
}));

import { SolutionGraphView } from "../SolutionGraphView";

const ROUTING_GRAPH = {
  nodes: ["s1", "c1", "d1", "e1"],
  layers: { s1: 0, c1: 1, d1: 2, e1: 3 },
  edges: [
    { variable: "xsc_s1_c1_k1", source: "s1", target: "c1", group: "k1", value: 1, family: "xsc" },
    { variable: "xcd_c1_d1_k1", source: "c1", target: "d1", group: "k1", value: 1, family: "xcd" },
    { variable: "xde_d1_e1_k1", source: "d1", target: "e1", group: "k1", value: 1, family: "xde" },
  ],
  groups: ["k1"],
  families: ["xcd", "xde", "xsc"],
  candidate_count: 12,
  active_count: 3,
  truncated: false,
  is_network: true,
  computed: true,
  note: null,
};

beforeEach(() => {
  getExecutionSolutionGraph.mockReset();
});

describe("SolutionGraphView", () => {
  it("draws a node per label and an edge per active variable", async () => {
    getExecutionSolutionGraph.mockResolvedValue(ROUTING_GRAPH);
    const { container } = render(<SolutionGraphView executionId="exe_1" />);

    await waitFor(() => expect(screen.getByTestId("solution-graph")).toBeInTheDocument());
    expect(container.querySelectorAll("ellipse")).toHaveLength(4);
    // One path per edge (the arrowhead markers are <marker><path>, inside <defs>).
    expect(container.querySelectorAll("svg > path")).toHaveLength(3);
    for (const label of ["s1", "c1", "d1", "e1"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("says how many of the possible connections are used", async () => {
    getExecutionSolutionGraph.mockResolvedValue(ROUTING_GRAPH);
    render(<SolutionGraphView executionId="exe_1" />);
    await waitFor(() =>
      expect(screen.getByText("solve.execution.solutionGraph.summaryNetwork")).toBeInTheDocument()
    );
  });

  it("calls a disjoint graph an assignment, not a network", async () => {
    getExecutionSolutionGraph.mockResolvedValue({
      ...ROUTING_GRAPH,
      is_network: false,
      groups: [],
    });
    render(<SolutionGraphView executionId="exe_1" />);
    await waitFor(() =>
      expect(
        screen.getByText("solve.execution.solutionGraph.summaryAssignment")
      ).toBeInTheDocument()
    );
  });

  // The axis is flow order. A reader who takes it for geography would be misled,
  // so the disclaimer is on screen rather than in a tooltip.
  it("states that the layout is not geographic", async () => {
    getExecutionSolutionGraph.mockResolvedValue(ROUTING_GRAPH);
    render(<SolutionGraphView executionId="exe_1" />);
    await waitFor(() =>
      expect(screen.getByText("solve.execution.solutionGraph.layoutNote")).toBeInTheDocument()
    );
  });

  it("offers one legend entry per group", async () => {
    getExecutionSolutionGraph.mockResolvedValue({
      ...ROUTING_GRAPH,
      groups: ["k1", "k2"],
    });
    render(<SolutionGraphView executionId="exe_1" />);
    await waitFor(() => expect(screen.getByTestId("solution-graph-legend")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "k1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "k2" })).toBeInTheDocument();
  });

  it("hides the legend when the edges carry no group", async () => {
    getExecutionSolutionGraph.mockResolvedValue({ ...ROUTING_GRAPH, groups: [] });
    render(<SolutionGraphView executionId="exe_1" />);
    await waitFor(() => expect(screen.getByTestId("solution-graph")).toBeInTheDocument());
    expect(screen.queryByTestId("solution-graph-legend")).not.toBeInTheDocument();
  });

  it("reports truncation instead of quietly drawing a subset", async () => {
    getExecutionSolutionGraph.mockResolvedValue({
      ...ROUTING_GRAPH,
      truncated: true,
      active_count: 900,
    });
    render(<SolutionGraphView executionId="exe_1" />);
    await waitFor(() =>
      expect(screen.getByText("solve.execution.solutionGraph.truncated")).toBeInTheDocument()
    );
  });
});

describe("SolutionGraphView refusal", () => {
  // Rendering nothing — heading included — is the point: a model with no graph is
  // healthy, and an empty frame would imply it failed at something.
  it("renders nothing when the backend reports no graph", async () => {
    getExecutionSolutionGraph.mockResolvedValue({
      ...ROUTING_GRAPH,
      computed: false,
      edges: [],
      nodes: [],
      note: "no edge-shaped variable family in this model",
    });
    const { container } = render(<SolutionGraphView executionId="exe_1" />);
    await waitFor(() => expect(getExecutionSolutionGraph).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText("solve.execution.solutionGraph.title")).not.toBeInTheDocument();
  });

  it("renders nothing when computed is true but no edge survived", async () => {
    getExecutionSolutionGraph.mockResolvedValue({ ...ROUTING_GRAPH, edges: [], nodes: [] });
    const { container } = render(<SolutionGraphView executionId="exe_1" />);
    await waitFor(() => expect(getExecutionSolutionGraph).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  // A bonus view must never take the page down with it.
  it("renders nothing when the request fails", async () => {
    getExecutionSolutionGraph.mockRejectedValue(new Error("boom"));
    const { container } = render(<SolutionGraphView executionId="exe_1" />);
    await waitFor(() => expect(getExecutionSolutionGraph).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
