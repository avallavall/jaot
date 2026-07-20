import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { SolutionExplorerTable } from "../SolutionExplorerTable";
import { StructuredSolutionView } from "../StructuredSolutionView";
import { ExecutionComparisonView } from "../ExecutionComparisonView";
import { SensitivityTab } from "../SensitivityTab";
import type { ModelExecution } from "@/lib/types";
import en from "../../../../messages/en.json";

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

function wrap(ui: React.ReactNode) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      {ui}
    </NextIntlClientProvider>
  );
}

describe("G9 — non-zero default toggles", () => {
  describe("SolutionExplorerTable", () => {
    const variables = [
      { name: "x_active", type: "continuous" as const, value: 3.5 },
      { name: "y_zero", type: "binary" as const, value: 0 },
      { name: "z_active", type: "integer" as const, value: 2 },
    ];

    it("hides zero-valued variables by default and reveals them on toggle", () => {
      wrap(<SolutionExplorerTable variables={variables} />);
      // Default ON → the zero row is hidden.
      expect(screen.getByText("x_active")).toBeInTheDocument();
      expect(screen.getByText("z_active")).toBeInTheDocument();
      expect(screen.queryByText("y_zero")).not.toBeInTheDocument();

      const toggle = screen.getByTestId("explorer-nonzero-toggle");
      expect(toggle).toBeChecked();
      fireEvent.click(toggle);
      expect(screen.getByText("y_zero")).toBeInTheDocument();
    });
  });

  describe("ExecutionComparisonView", () => {
    const mk = (id: string, vars: { name: string; value: number }[]): ModelExecution =>
      ({
        id,
        organization_model_id: null,
        status: "completed",
        created_at: "2026-07-16T10:00:00Z",
        result_data: {
          variables: vars.map((v) => ({ name: v.name, type: "continuous", value: v.value })),
        },
        input_data: { objective: { sense: "minimize" } },
      }) as unknown as ModelExecution;

    const a = mk("exec_aaaa1111", [
      { name: "same_var", value: 5 },
      { name: "changed_var", value: 1 },
    ]);
    const b = mk("exec_bbbb2222", [
      { name: "same_var", value: 5 },
      { name: "changed_var", value: 9 },
    ]);

    it("shows only changed variables by default and all on toggle", () => {
      wrap(<ExecutionComparisonView executionA={a} executionB={b} />);
      const table = screen.getByRole("table");
      expect(within(table).getByText("changed_var")).toBeInTheDocument();
      expect(within(table).queryByText("same_var")).not.toBeInTheDocument();

      const toggle = screen.getByTestId("comparison-changes-toggle");
      expect(toggle).toBeChecked();
      fireEvent.click(toggle);
      expect(within(table).getByText("same_var")).toBeInTheDocument();
    });
  });

  describe("SensitivityTab", () => {
    const sensitivity = {
      constraints: [],
      is_approximate: false,
      variables: [
        { name: "basic_var", reduced_cost: 0, is_at_bound: false, is_approximate: false },
        { name: "bound_var", reduced_cost: 4.2, is_at_bound: true, is_approximate: false },
      ],
    } as unknown as Parameters<typeof SensitivityTab>[0]["sensitivity"];

    it("collapses a degenerate shadow-price wall into per-value groups", () => {
      // 20 constraints, all with the SAME dual (the 100×100 assignment pathology):
      // a bar chart of identical bars carries zero information — the tab must render
      // one grouped row per distinct value plus the degeneracy note, not the chart.
      const degenerate = {
        constraints: Array.from({ length: 20 }, (_, i) => ({
          name: `c1_${i}`,
          shadow_price: 1.0,
          is_binding: true,
        })),
        is_approximate: true,
        variables: [],
      } as unknown as Parameters<typeof SensitivityTab>[0]["sensitivity"];
      wrap(<SensitivityTab sensitivity={degenerate} />);
      const groups = screen.getByTestId("sensitivity-shadow-groups");
      expect(groups).toBeInTheDocument();
      // ONE row for the single distinct value (1.0000), not twenty identical bars…
      expect(within(groups).getAllByText("1.0000")).toHaveLength(1);
      // …and no per-constraint wall.
      expect(screen.queryByText("c1_7")).not.toBeInTheDocument();
    });

    it("filters by REDUCED COST (not value): a zero-rc basic var is hidden by default", () => {
      wrap(<SensitivityTab sensitivity={sensitivity} />);
      expect(screen.getByText("bound_var")).toBeInTheDocument();
      expect(screen.queryByText("basic_var")).not.toBeInTheDocument();

      const toggle = screen.getByTestId("sensitivity-nonzero-rc-toggle");
      expect(toggle).toBeChecked();
      fireEvent.click(toggle);
      expect(screen.getByText("basic_var")).toBeInTheDocument();
    });
  });
});

describe("StructuredSolutionView (A1b — grouped by recovered index structure)", () => {
  const structured = [
    { name: "assign_v3_o107", type: "binary" as const, value: 1, family: "assign", index_tuple: ["v3", "o107"] },
    { name: "assign_v3_o12", type: "binary" as const, value: 1, family: "assign", index_tuple: ["v3", "o12"] },
    { name: "assign_v1_o44", type: "binary" as const, value: 0, family: "assign", index_tuple: ["v1", "o44"] },
  ];

  it("leads with the grouped view and hides the zero assignment by default", () => {
    wrap(<StructuredSolutionView variables={structured} />);
    expect(screen.getByTestId("structured-groups")).toBeInTheDocument();
    expect(screen.getByText("assign")).toBeInTheDocument();
    expect(screen.getByText("o107")).toBeInTheDocument();
    // nonzero default ON → the value-0 assignment (v1 → o44) is filtered out
    expect(screen.queryByText("o44")).not.toBeInTheDocument();
    // switching to the full table brings back the flat explorer (+ sensitivity)
    fireEvent.click(screen.getByTestId("structured-view-table"));
    expect(screen.getByTestId("explorer-nonzero-toggle")).toBeInTheDocument();
  });

  it("caps a huge grouped render behind an explicit 'show all'", () => {
    // 600 non-zero structured variables: the grouped view must render a bounded
    // prefix (500) + a banner, and only mount everything on the opt-in click —
    // an unbounded render froze the page on real 20k-variable solutions.
    const huge = Array.from({ length: 600 }, (_, i) => ({
      name: `assign_v1_o${i}`,
      type: "binary" as const,
      value: 1,
      family: "assign",
      index_tuple: ["v1", `o${i}`],
    }));
    wrap(<StructuredSolutionView variables={huge} />);
    expect(screen.getByTestId("structured-render-cap")).toBeInTheDocument();
    expect(screen.queryByText("o499")).toBeInTheDocument();
    expect(screen.queryByText("o500")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("structured-show-all"));
    expect(screen.queryByTestId("structured-render-cap")).not.toBeInTheDocument();
    expect(screen.queryByText("o599")).toBeInTheDocument();
  });

  it("falls back to the flat table when no structure was recovered", () => {
    wrap(
      <StructuredSolutionView
        variables={[{ name: "x", type: "continuous" as const, value: 3.5 }]}
      />,
    );
    expect(screen.queryByTestId("structured-groups")).not.toBeInTheDocument();
    expect(screen.getByTestId("explorer-nonzero-toggle")).toBeInTheDocument();
  });
});
