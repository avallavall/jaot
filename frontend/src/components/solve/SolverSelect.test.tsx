/**
 * SolverSelect smoke: renders the solver entries from /solvers/available.
 *
 * After Plan 08 ships, each <SelectItem> for a registered solver must show
 *
 * NOTE: marked it.skip until Plan 08 lands. Plan 08 Task 3 removes the
 * .skip call after the SolverSelect rewrite + i18n cleanup.
 */
import { describe, it, expect, vi, afterEach } from "vitest";

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

/**
 * v3.2 — the picker names what the CHOSEN solver will not deliver, so the
 * trade-off is visible before the solve instead of as an empty panel after it.
 *
 * The suite mocks next-intl globally to echo `namespace.key` (see
 * src/test/setup.tsx), so these assert on the KEYS that get rendered — which is
 * the decision under test — rather than on translated copy.
 */
describe("SolverSelect capability notices", () => {
  const messages = {
    solvers: {
      selectLabel: "Solver",
      selectPlaceholder: "Select",
      loadingLabel: "Loading",
      scip: { description: "SCIP solver" },
      hexaly: { description: "Hexaly solver" },
      auto: { label: "Auto", hint: "Auto-routing" },
      noSensitivityNotice: "{solver} computes no shadow prices.",
      noProgressNotice: "{solver} reports no progress while it searches.",
    },
  };

  const SOLVERS = [
    {
      name: "scip",
      available: true,
      capabilities: { sensitivity: true, warm_start: true, quadratic: true, progress: true },
    },
    {
      name: "hexaly",
      available: true,
      capabilities: { sensitivity: false, warm_start: true, quadratic: true, progress: false },
    },
    // A solver whose adapter declaration could not be read.
    { name: "mystery", available: true },
  ];

  afterEach(async () => {
    const { cleanup } = await import("@testing-library/react");
    cleanup();
  });

  async function renderWith(solverName: string) {
    const { render, screen } = await import("@testing-library/react");
    const { NextIntlClientProvider } = await import("next-intl");
    const { SolverSelect } = await import("./SolverSelect");
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <SolverSelect
          solverName={solverName}
          onSolverChange={vi.fn()}
          loading={false}
          availableSolvers={SOLVERS}
        />
      </NextIntlClientProvider>,
    );
    return screen;
  }

  it("names both missing capabilities for a solver that has neither", async () => {
    const screen = await renderWith("hexaly");
    const notice = screen.getByTestId("solver-capability-notice");
    expect(notice).toHaveTextContent("solvers.noSensitivityNotice");
    expect(notice).toHaveTextContent("solvers.noProgressNotice");
  });

  it("says nothing for a solver that delivers everything the UI surfaces", async () => {
    const screen = await renderWith("scip");
    expect(screen.queryByTestId("solver-capability-notice")).not.toBeInTheDocument();
  });

  // The effective solver under "auto" is chosen by the backend per problem, so
  // promising anything about it up front would be a guess.
  it("says nothing under auto-routing", async () => {
    const screen = await renderWith("auto");
    expect(screen.queryByTestId("solver-capability-notice")).not.toBeInTheDocument();
  });

  // Unknown capabilities must read as "not known", never as "not supported" —
  // otherwise an unreadable declaration would libel a perfectly capable solver.
  it("says nothing when the solver reports no capabilities at all", async () => {
    const screen = await renderWith("mystery");
    expect(screen.queryByTestId("solver-capability-notice")).not.toBeInTheDocument();
  });
});
