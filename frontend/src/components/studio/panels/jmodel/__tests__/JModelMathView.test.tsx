import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

import { JModelMathView } from "../JModelMathView";
import type { DslLatexResult } from "@/lib/types";

// Isolate the component from KaTeX internals: render the raw LaTeX so we can assert
// what strings the backend render was asked to typeset.
vi.mock("react-katex", () => ({
  BlockMath: ({ math }: { math: string }) => <div data-testid="katex">{math}</div>,
}));

vi.mock("@/lib/api", () => ({
  api: { latexDsl: vi.fn() },
}));

import { api } from "@/lib/api";

const latexDsl = api.latexDsl as unknown as ReturnType<typeof vi.fn>;

const OK_MODEL: DslLatexResult = {
  ok: true,
  model: {
    objective: { latex: "\\min \\quad \\sum_{i \\in I} x_{i}", label: "obj" },
    constraints: [{ latex: "x_{i} \\le 1 \\quad \\forall\\, i \\in I", label: "cap" }],
    variables: [{ latex: "x_{i} \\in \\{0, 1\\}", label: "x" }],
  },
};

describe("JModelMathView", () => {
  beforeEach(() => {
    latexDsl.mockReset();
  });

  it("shows an empty hint and does not fetch for a blank source", () => {
    render(<JModelMathView source="   " active />);
    expect(screen.getByText("studio.jmodelMathEmpty")).toBeInTheDocument();
    expect(latexDsl).not.toHaveBeenCalled();
  });

  it("does not fetch while the pane is inactive", () => {
    render(<JModelMathView source="var x >= 0;" active={false} />);
    expect(latexDsl).not.toHaveBeenCalled();
  });

  it("renders objective, constraint and domain sections from the rendered model", async () => {
    latexDsl.mockResolvedValue(OK_MODEL);
    render(<JModelMathView source="minimize obj: sum{i in I} x[i];" active />);

    expect(await screen.findByText("studio.jmodelMathObjective")).toBeInTheDocument();
    expect(screen.getByText("studio.jmodelMathSubjectTo")).toBeInTheDocument();
    expect(screen.getByText("studio.jmodelMathDomains")).toBeInTheDocument();

    const rendered = screen.getAllByTestId("katex").map((n) => n.textContent);
    expect(rendered).toContain("\\min \\quad \\sum_{i \\in I} x_{i}");
    expect(rendered).toContain("x_{i} \\le 1 \\quad \\forall\\, i \\in I");
    expect(rendered).toContain("x_{i} \\in \\{0, 1\\}");
    // The constraint's name is shown as a caption.
    expect(screen.getByText("(cap)")).toBeInTheDocument();
    expect(latexDsl).toHaveBeenCalledWith("minimize obj: sum{i in I} x[i];");
  });

  it("keeps the last valid render and flags it stale when the source stops parsing", async () => {
    latexDsl.mockResolvedValueOnce(OK_MODEL);
    const { rerender } = render(<JModelMathView source="minimize obj: x;" active />);
    await screen.findByText("studio.jmodelMathObjective");

    // The next edit fails to parse: keep the notation, add a stale hint.
    latexDsl.mockResolvedValueOnce({
      ok: false,
      error: { message: "expected ';'", position: 5 },
    });
    rerender(<JModelMathView source="minimize obj: x" active />);

    await waitFor(() => expect(screen.getByText("studio.jmodelMathInvalid")).toBeInTheDocument());
    // The objective section is still on screen (dimmed), not replaced by an error box.
    expect(screen.getByText("studio.jmodelMathObjective")).toBeInTheDocument();
  });

  it("shows the invalid hint (no sections) when the first source never parses", async () => {
    latexDsl.mockResolvedValue({ ok: false, error: { message: "boom", position: 0 } });
    render(<JModelMathView source="not a model" active />);
    await waitFor(() => expect(screen.getByText("studio.jmodelMathInvalid")).toBeInTheDocument());
    expect(screen.queryByText("studio.jmodelMathObjective")).not.toBeInTheDocument();
  });
});
