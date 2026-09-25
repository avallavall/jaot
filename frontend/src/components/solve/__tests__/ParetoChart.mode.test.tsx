import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

import type { MultiObjectiveResult } from "@/lib/types";
import { ParetoChart } from "../ParetoChart";

/**
 * The chart printed its mode as the raw value, "Weighted", on a Spanish page.
 * The mode is a translated name now.
 */
describe("ParetoChart mode", () => {
  it("prints the translated method name, not the raw value", () => {
    const result = {
      mode: "weighted",
      n_solved: 2,
      labels: ["P", "E"],
      pareto_points: [
        { f1: 12, f2: 8, objective_values: { P: 12, E: 8 }, solution: { x: 4 } },
        { f1: 44, f2: 34, objective_values: { P: 44, E: 34 }, solution: { x: 8 } },
      ],
    } as unknown as MultiObjectiveResult;

    render(<ParetoChart result={result} />);

    expect(screen.getByText("solve.charts.pareto.modeName.weighted")).toBeInTheDocument();
    expect(screen.queryByText("weighted")).toBeNull();
  });
});
