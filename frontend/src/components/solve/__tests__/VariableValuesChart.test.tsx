import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// recharts needs a non-zero layout size in jsdom; stub the responsive wrapper.
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ width: 800, height: 400 }}>{children}</div>
    ),
  };
});

import { VariableValuesChart } from "../VariableValuesChart";
import type { VariableSolution } from "@/lib/types";

function v(name: string, value: number, type = "binary"): VariableSolution {
  return { name, value, type } as VariableSolution;
}

describe("VariableValuesChart — A4 aggregate for identical bars", () => {
  const binaryDominant = [
    v("a_1", 1),
    v("a_2", 1),
    v("a_3", 1),
    v("a_4", 0),
    v("a_5", 0),
  ];

  it("collapses to an aggregate when every non-zero bar is the same length", () => {
    render(<VariableValuesChart variables={binaryDominant} />);
    expect(screen.getByTestId("variable-values-aggregate")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument(); // 3 non-zero at 1.0
    expect(screen.getByText("2")).toBeInTheDocument(); // 2 at zero
  });

  it("reveals the chart on demand", () => {
    render(<VariableValuesChart variables={binaryDominant} />);
    fireEvent.click(screen.getByTestId("variable-values-show-chart"));
    expect(screen.queryByTestId("variable-values-aggregate")).not.toBeInTheDocument();
  });

  it("keeps the bar chart when magnitudes vary (bar length is informative)", () => {
    const varied = [v("f_1", 12.5, "continuous"), v("f_2", 3.2, "continuous"), v("f_3", 40, "continuous")];
    render(<VariableValuesChart variables={varied} />);
    expect(screen.queryByTestId("variable-values-aggregate")).not.toBeInTheDocument();
  });
});
