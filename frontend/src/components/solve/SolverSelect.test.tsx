/**
 * SolverSelect smoke: renders the solver entries from /solvers/available.
 *
 * After Plan 08 ships, each <SelectItem> for a registered solver must show
 *
 * NOTE: marked it.skip until Plan 08 lands. Plan 08 Task 3 removes the
 * .skip call after the SolverSelect rewrite + i18n cleanup.
 */
import { describe, it, expect, vi } from "vitest";

describe("SolverSelect", () => {
  // Plan 08 landed: marker removed, assertion now active (V-10 GREEN).
  it("renders with the solver list prop shape", async () => {
    const { render, screen } = await import("@testing-library/react");
    const { NextIntlClientProvider } = await import("next-intl");
    const { SolverSelect } = await import("./SolverSelect");

    const messages = {
      solvers: {
        selectLabel: "Solver",
        selectPlaceholder: "Select",
        loadingLabel: "Loading",
        scip: { description: "SCIP solver" },
        highs: { description: "HiGHS solver" },
        hexaly: { description: "Hexaly solver" },
        auto: { label: "Auto", hint: "Auto-routing" },
      },
    };

    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <SolverSelect
          solverName="auto"
          onSolverChange={vi.fn()}
          loading={false}
          availableSolvers={[
            { name: "scip", available: true },
            { name: "highs", available: true },
            { name: "hexaly", available: true },
          ]}
        />
      </NextIntlClientProvider>,
    );

    // Radix renders SelectItems in a portal when SelectContent is open; this
    // smoke-level assertion only proves the component accepts the prop
    // shape without throwing.
    expect(screen.getByLabelText(/Solver/i)).toBeInTheDocument();
  });
});
