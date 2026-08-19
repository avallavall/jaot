import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import React from "react";

/**
 * Four of the Solution Explorer's seven columns could never hold a value.
 * Lower Bound and Upper Bound were em-dashes written into the JSX; Binding and
 * Slack always read "N/A" under a tooltip blaming MIP problems, on a run that
 * was a pure LP with two continuous variables. The bounds were in the
 * execution's own `input_data.variables` the whole time.
 */

import { SolutionExplorerTable } from "../SolutionExplorerTable";
import en from "../../../../messages/en.json";

// The suite's setup replaces next-intl with a stub that echoes the key path, so
// the assertions below name keys rather than English. Whether every key exists
// in all five locales is `npm run check-i18n`'s job.
function wrap(ui: React.ReactNode) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      {ui}
    </NextIntlClientProvider>
  );
}

/** The cells of the row for one variable, in column order. */
function cellsFor(name: string): string[] {
  const row = screen.getByText(name).closest("tr") as HTMLElement;
  return within(row)
    .getAllByRole("cell")
    .map((cell) => cell.textContent?.trim() ?? "");
}

const VARIABLES = [
  { name: "x", type: "continuous" as const, value: 3 },
  { name: "y", type: "continuous" as const, value: 1.5 },
];

const BOUNDS = {
  x: { lower: 0, upper: 3 },
  y: { lower: 0, upper: 10 },
};

describe("the Solution Explorer's bound columns", () => {
  // CONTRACT-TEST: no column of the explorer is a permanent placeholder
  it("shows the range each variable was declared with", () => {
    wrap(<SolutionExplorerTable variables={VARIABLES} bounds={BOUNDS} />);

    const [, , value, lower, upper] = cellsFor("x");
    expect(value).toBe("3");
    expect(lower).toBe("0");
    expect(upper).toBe("3");
  });

  it("names the bound a variable was pushed onto, and the room left when it was not", () => {
    wrap(<SolutionExplorerTable variables={VARIABLES} bounds={BOUNDS} />);

    const [, , , , , bindingX, slackX] = cellsFor("x");
    expect(bindingX).toBe("solve.explorer.atUpperBound");
    expect(slackX).toBe("0");

    const [, , , , , bindingY, slackY] = cellsFor("y");
    expect(bindingY).toBe("—");
    // The decimal separator follows the test environment locale.
    expect(slackY).toMatch(/^1[.,]5$/);
  });

  // A run recorded before the page passed its bounds down, or one whose payload
  // is not on the page. Saying nothing is right; saying "N/A because this is a
  // MIP" about a pure LP was not.
  it("says nothing rather than guessing when the run carries no bounds", () => {
    wrap(<SolutionExplorerTable variables={VARIABLES} />);

    const [, , value, lower, upper, binding, slack] = cellsFor("x");
    expect(value).toBe("3");
    expect([lower, upper, binding, slack]).toEqual(["—", "—", "—", "—"]);
  });
});
