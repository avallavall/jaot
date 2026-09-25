import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { apiRequest } = vi.hoisted(() => ({ apiRequest: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: { request: apiRequest },
}));

import AdminExecutionsPage from "../page";

const row = (id: string, over: Record<string, unknown> = {}) => ({
  id,
  organization_id: "org_1",
  organization_name: "Acme",
  model_project_id: null,
  model_name: "QA infeasible blend",
  status: "completed",
  solver_name: "highs",
  execution_time_ms: 120,
  created_at: "2026-09-24T10:00:00Z",
  ...over,
});

const answer = (items: unknown[]) => ({
  items,
  total: items.length,
  page: 1,
  page_size: 20,
  pages: 1,
  stats: { total: items.length, avg_execution_time_ms: 120 },
});

describe("Admin executions page", () => {
  // The Radix select relies on pointer capture and scrollIntoView, absent in jsdom.
  beforeAll(() => {
    Element.prototype.hasPointerCapture = Element.prototype.hasPointerCapture ?? (() => false);
    Element.prototype.setPointerCapture = Element.prototype.setPointerCapture ?? (() => {});
    Element.prototype.releasePointerCapture =
      Element.prototype.releasePointerCapture ?? (() => {});
    Element.prototype.scrollIntoView = Element.prototype.scrollIntoView ?? (() => {});
  });

  // The table had no solver column, so an admin could not see which of the
  // five solvers ran a run. Brand names, as everywhere else in the product.
  it("says which solver ran each row, by its brand name", async () => {
    apiRequest.mockResolvedValue(answer([row("exe_1"), row("exe_2", { solver_name: "jaos" })]));

    render(<AdminExecutionsPage />);

    expect(
      await screen.findByRole("columnheader", { name: "admin.executions.tableHeaders.solver" }),
    ).toBeInTheDocument();
    const rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("HiGHS")).toBeInTheDocument();
    expect(within(rows[1]).getByText("JAOS")).toBeInTheDocument();
  });

  it("shows the name the server gives a run of no saved model", async () => {
    apiRequest.mockResolvedValue(answer([row("exe_1")]));

    render(<AdminExecutionsPage />);

    expect(await screen.findByText("QA infeasible blend")).toBeInTheDocument();
  });

  it("asks the server for one solver's runs", async () => {
    apiRequest.mockResolvedValue(answer([row("exe_1")]));
    const user = userEvent.setup();

    render(<AdminExecutionsPage />);
    await waitFor(() => expect(apiRequest).toHaveBeenCalled());

    await user.click(screen.getByRole("combobox", { name: "admin.executions.tableHeaders.solver" }));
    await user.click(screen.getByRole("option", { name: "JAOS" }));

    await waitFor(() => {
      const urls = apiRequest.mock.calls.map((c) => String(c[0]));
      expect(urls.some((u) => u.includes("solver=jaos"))).toBe(true);
    });
  });
});
