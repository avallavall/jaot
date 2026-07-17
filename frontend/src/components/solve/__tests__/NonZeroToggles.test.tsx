import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { SolutionExplorerTable } from "../SolutionExplorerTable";
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
