/**
 * Reaching the comparison view.
 *
 * `/solve/executions/compare` is a finished screen that nothing linked to: the
 * only way in was typing two execution ids into a free-text box on the analytics
 * page, so in practice it did not exist. The owner chose to surface it rather
 * than delete it (2026-08-02). These tests pin the way in.
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

const { mockList, mockPush } = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockPush: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: { getAllExecutions: mockList } }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mockPush }) }));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
  useRouter: () => ({ push: mockPush }),
}));

import ExecutionsPage from "../page";

const row = (id: string) => ({
  id,
  status: "completed",
  solver_status: "optimal",
  objective_value: 1,
  execution_time_ms: 10,
  created_at: "2026-08-01T10:00:00Z",
  origin: "manual",
});

describe("Executions list — reaching the comparison view", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockList.mockResolvedValue({ items: [row("exe_a"), row("exe_b"), row("exe_c")], total: 3 });
  });

  it("offers no comparison until something is selected", async () => {
    render(<ExecutionsPage />);
    await screen.findAllByTestId("execution-select");
    expect(screen.queryByTestId("executions-compare")).not.toBeInTheDocument();
  });

  // CONTRACT-TEST: the compare view takes exactly two runs (`?a=&b=`).
  it("needs exactly two, and navigates with both ids", async () => {
    render(<ExecutionsPage />);
    const boxes = await screen.findAllByTestId("execution-select");

    fireEvent.click(boxes[0]);
    expect(screen.getByTestId("executions-compare")).toBeDisabled();

    fireEvent.click(boxes[1]);
    const compare = screen.getByTestId("executions-compare");
    expect(compare).toBeEnabled();

    fireEvent.click(compare);
    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith("/solve/executions/compare?a=exe_a&b=exe_b"),
    );
  });

  // Selecting a third would otherwise either be ignored (a click that does
  // nothing) or produce a selection the target screen cannot render.
  it("keeps the last two when a third is picked", async () => {
    render(<ExecutionsPage />);
    const boxes = await screen.findAllByTestId("execution-select");

    fireEvent.click(boxes[0]);
    fireEvent.click(boxes[1]);
    fireEvent.click(boxes[2]);

    fireEvent.click(screen.getByTestId("executions-compare"));
    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith("/solve/executions/compare?a=exe_b&b=exe_c"),
    );
  });
});
