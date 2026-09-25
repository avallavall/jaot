/**
 * What the custom solve page shows, found driving it in Spanish (2026-09-25):
 *
 * - The solution grid put two pairs on a line, so "x 2 y 1" read as x's value
 *   next to y's name.
 * - After editing the JSON, "Valid Problem" and the old answer stayed on screen.
 * - Errors printed the API's English: "{'q'}" and "EXPR_PARSE_ERROR".
 * - The verdict read "Optimal" and the time "0.65 ms" on a Spanish page.
 * - A 3,000-variable model drew every variable, 2,897 of them zero, and gave no
 *   way to the saved run.
 * - "Back to Templates" went to My Models.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import React from "react";

const { solve, validateProblem, push } = vi.hoisted(() => ({
  solve: vi.fn(),
  validateProblem: vi.fn(),
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

// The key path plus the values it was given; the page is in Spanish.
vi.mock("next-intl", () => ({
  useTranslations: (ns: string) => {
    const t = (key: string, values?: Record<string, unknown>) =>
      `${ns}.${key}${values ? ` ${JSON.stringify(values)}` : ""}`;
    return Object.assign(t, { rich: t, has: () => true });
  },
  useLocale: () => "es",
}));

vi.mock("@/lib/api", () => ({
  api: { solve, validateProblem },
  ApiError: class ApiError extends Error {},
}));

vi.mock("@/hooks/useSolvers", () => ({
  useSolvers: () => ({
    solverName: "auto",
    setSolverName: vi.fn(),
    availableSolvers: [],
    solversLoading: false,
  }),
  useSolverCapabilities: () => undefined,
}));

vi.mock("@/components/solve/SolverSelect", () => ({ SolverSelect: () => null }));

vi.mock("@/i18n/navigation", () => ({
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

import CustomSolvePage from "../custom/page";

function aResult(overrides: Record<string, unknown> = {}) {
  return {
    execution_id: "exe_custom",
    status: "optimal",
    objective_value: 9.5,
    solve_time_seconds: 0.00065,
    solution: { x: 2, y: 1, z: 1, w: 0.5 },
    variables: [],
    solver_used: "jaos",
    sensitivity: null,
    ...overrides,
  };
}

async function solveOnce(result: Record<string, unknown>) {
  solve.mockResolvedValueOnce(result);
  fireEvent.click(screen.getByText("solve.custom.solve"));
  await waitFor(() => expect(solve).toHaveBeenCalled());
  await screen.findByTestId("custom-status");
}

function editor(): HTMLTextAreaElement {
  return screen.getByPlaceholderText("solve.custom.enterProblemDefinition") as HTMLTextAreaElement;
}

describe("the custom solve page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    render(<CustomSolvePage />);
  });

  it("goes back to the templates when it says Templates", () => {
    fireEvent.click(screen.getByText("solve.custom.backToTemplates"));

    expect(push).toHaveBeenCalledWith("/studio/templates");
  });

  it("puts each value on the row of its own variable", async () => {
    await solveOnce(aResult());

    const rows = within(screen.getByTestId("custom-solution")).getAllByRole("row");
    const cells = rows.map((row) =>
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    );
    expect(cells).toEqual([
      ["x", "2"],
      ["y", "1"],
      ["z", "1"],
      ["w", "0,5"],
    ]);
  });

  it("names the verdict in the page's words and the time in its number format", async () => {
    await solveOnce(aResult());

    expect(screen.getByTestId("custom-status").textContent).toBe("solverCompare.status.optimal");
    expect(screen.getByTestId("custom-solve-time").textContent).toContain('"ms":"0,65"');
  });

  it("clears the verdict and the answer when the JSON changes", async () => {
    validateProblem.mockResolvedValueOnce({ valid: true, errors: [], warnings: [] });
    fireEvent.click(screen.getByText("solve.custom.validate"));
    await screen.findByText("solve.custom.validProblem");
    await solveOnce(aResult());

    fireEvent.change(editor(), { target: { value: '{"name": "edited"}' } });

    expect(screen.queryByText("solve.custom.validProblem")).toBeNull();
    expect(screen.queryByTestId("custom-status")).toBeNull();
  });

  it("shows validation errors as translated sentences, not the API's English", async () => {
    const english = "Constraint c1 references undefined variables: {'q'}";
    validateProblem.mockResolvedValueOnce({
      valid: false,
      errors: [english],
      warnings: [],
      issues: [
        {
          code: "problem.constraint_undefined_variables",
          params: { constraint: "c1", names: "q" },
          message: english,
        },
      ],
    });

    fireEvent.click(screen.getByText("solve.custom.validate"));

    const list = await screen.findByTestId("custom-validation-errors");
    expect(list.textContent).toContain("errors.codes.problem.constraint_undefined_variables");
    expect(list.textContent).not.toContain("{'q'}");
  });

  it("lists non-zero values by default, caps the list and links to the saved run", async () => {
    const solution: Record<string, number> = {};
    for (let i = 0; i < 3000; i++) solution[`v${i}`] = i < 300 ? 1 : 0;
    await solveOnce(aResult({ solution }));

    const box = screen.getByTestId("custom-solution");
    expect(within(box).getAllByRole("row")).toHaveLength(200);
    const footer = screen.getByTestId("custom-solution-footer");
    expect(footer.textContent).toContain('"shown":200,"total":300');
    const link = within(footer).getByText("solve.custom.openSavedRun").closest("a");
    expect(link?.getAttribute("href")).toBe("/solve/executions/exe_custom");

    fireEvent.click(screen.getByTestId("custom-solution-nonzero"));

    expect(within(box).getAllByRole("row")).toHaveLength(200);
    expect(footer.textContent).toContain('"shown":200,"total":3000');
  });
});
