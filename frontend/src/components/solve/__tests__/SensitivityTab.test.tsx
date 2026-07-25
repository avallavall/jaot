/**
 * SensitivityTab — why the tab is empty (v3.2).
 *
 * An empty Sensitivity tab has two very different causes: the run genuinely
 * produced no duals, or the solver that ran it does not compute duals at all.
 * "No sensitivity data available" hid both behind one shrug. These tests pin the
 * rule that decides which explanation is honest.
 *
 * next-intl is mocked suite-wide to echo `namespace.key` (src/test/setup.tsx),
 * so assertions target the key that gets rendered, not translated copy.
 */
import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";

import { SensitivityTab } from "../SensitivityTab";

const COMPUTES_DUALS = {
  sensitivity: true,
  warm_start: true,
  quadratic: true,
  progress: true,
};
const NO_DUALS = {
  sensitivity: false,
  warm_start: true,
  quadratic: true,
  progress: false,
};

describe("SensitivityTab empty state", () => {
  it("blames the solver when it declares it computes no duals", () => {
    render(<SensitivityTab sensitivity={null} solverName="hexaly" capabilities={NO_DUALS} />);
    expect(screen.getByTestId("sensitivity-empty")).toHaveTextContent(
      "solve.sensitivity.solverNoDuals"
    );
  });

  it("keeps the neutral wording when the solver could have computed duals", () => {
    render(<SensitivityTab sensitivity={null} solverName="scip" capabilities={COMPUTES_DUALS} />);
    expect(screen.getByTestId("sensitivity-empty")).toHaveTextContent("solve.sensitivity.noData");
  });

  // Unknown capabilities must read as "not known", never as "not supported":
  // an execution whose solver is no longer listed must not be blamed for it.
  it("keeps the neutral wording when capabilities are unknown", () => {
    render(<SensitivityTab sensitivity={null} solverName="mystery" />);
    expect(screen.getByTestId("sensitivity-empty")).toHaveTextContent("solve.sensitivity.noData");
  });

  it("keeps the neutral wording when there is no solver to name", () => {
    render(<SensitivityTab sensitivity={null} capabilities={NO_DUALS} />);
    expect(screen.getByTestId("sensitivity-empty")).toHaveTextContent("solve.sensitivity.noData");
  });

  // The explanation is for an EMPTY tab only — a solver flagged as dual-less
  // that somehow carries data must still render the data.
  it("renders the data rather than an excuse when sensitivity is present", () => {
    render(
      <SensitivityTab
        sensitivity={{
          constraints: [
            { name: "cap", shadow_price: 4, is_binding: true, is_approximate: false },
          ],
          is_approximate: false,
          objective_ranges: [],
          rhs_ranges: [],
          variables: [],
        }}
        solverName="hexaly"
        capabilities={NO_DUALS}
      />
    );
    expect(screen.queryByTestId("sensitivity-empty")).not.toBeInTheDocument();
    expect(screen.getByText("cap")).toBeInTheDocument();
  });
});
