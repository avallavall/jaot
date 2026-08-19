import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

/**
 * Completed 972 + Failed 27 + Timed Out 0 came to 999 under a Total Executions
 * of 1,002. The three cancelled runs were counted in the total and had no tile
 * of their own, so the parts did not account for the whole.
 */

import { AnalyticsStatusTiles } from "../AnalyticsStatusTiles";

function tile(status: string) {
  return screen.queryByTestId(`analytics-tile-${status}`);
}

/** What the row says, added up. */
function shownTotal() {
  return ["completed", "failed", "timeout", "cancelled", "running", "pending"]
    .map((s) => tile(s))
    .filter((el): el is HTMLElement => el !== null)
    .reduce((sum, el) => sum + Number(el.textContent?.match(/(\d+)\s*$/)?.[1] ?? 0), 0);
}

describe("the analytics status tiles", () => {
  // CONTRACT-TEST: the tiles add up to the total they sit under
  it("accounts for every run, cancelled ones included", () => {
    render(
      <AnalyticsStatusTiles
        byStatus={{ completed: 972, failed: 27, timeout: 0, cancelled: 3 }}
      />
    );

    expect(tile("cancelled")).toBeInTheDocument();
    expect(shownTotal()).toBe(1002);
  });

  it("accounts for runs that have not finished either", () => {
    render(
      <AnalyticsStatusTiles
        byStatus={{ completed: 4, failed: 1, timeout: 2, running: 3, pending: 1 }}
      />
    );

    expect(shownTotal()).toBe(11);
    expect(tile("running")).toBeInTheDocument();
    expect(tile("pending")).toBeInTheDocument();
  });

  // The three that were always there stay there, so the row does not jump
  // around as the reader changes period.
  it("keeps the three long-standing tiles even at zero", () => {
    render(<AnalyticsStatusTiles byStatus={{ completed: 5 }} />);

    expect(tile("completed")?.textContent).toContain("5");
    expect(tile("failed")?.textContent).toContain("0");
    expect(tile("timeout")?.textContent).toContain("0");
    // And says nothing about the three that hold nothing.
    expect(tile("cancelled")).not.toBeInTheDocument();
    expect(tile("running")).not.toBeInTheDocument();
    expect(tile("pending")).not.toBeInTheDocument();
  });

  it("survives a period with no runs at all", () => {
    render(<AnalyticsStatusTiles byStatus={undefined} />);
    expect(shownTotal()).toBe(0);
  });
});
