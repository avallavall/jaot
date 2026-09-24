import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { create } from "zustand";

/**
 * "Runs of this model" stayed one run behind (driving the studio, 2026-09-24):
 * it loaded once on mount and polled only while a run it already listed was
 * live, so a run started from this tab never appeared. It now reloads when the
 * tab's own solve session starts or ends.
 */

const { getProjectExecutions } = vi.hoisted(() => ({ getProjectExecutions: vi.fn() }));

vi.mock("@/lib/api", () => ({ api: { getProjectExecutions } }));
vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  useFormatter: () => ({ relativeTime: () => "just now", number: (n: number) => String(n) }),
  useNow: () => new Date("2026-09-24T21:05:00Z"),
}));
vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

interface FakeState {
  modelId: string;
  solveSession: { status: string; executionId: string | null };
}
const useFake = create<FakeState>(() => ({
  modelId: "mp_1",
  solveSession: { status: "idle", executionId: null },
}));
vi.mock("../../../store/useModelProjectStore", () => ({
  useModelProjectStore: <T,>(selector: (s: FakeState) => T) => useFake(selector),
}));

import { ProjectRunsCard } from "../ProjectRunsCard";

function run(id: string, solver: string) {
  return {
    id,
    status: "completed",
    created_at: "2026-09-24T21:00:00Z",
    objective_value: 450,
    execution_time_ms: 10,
    solver_used: solver,
    dataset_name: null,
  };
}

describe("ProjectRunsCard", () => {
  beforeEach(() => {
    getProjectExecutions.mockReset();
    useFake.setState({ solveSession: { status: "idle", executionId: null } });
  });

  it("shows a run started from this tab once it finishes", async () => {
    getProjectExecutions.mockResolvedValueOnce([run("exe_1", "jaos")]);
    render(<ProjectRunsCard />);
    await waitFor(() => expect(getProjectExecutions).toHaveBeenCalledTimes(1));

    getProjectExecutions.mockResolvedValue([run("exe_2", "scip"), run("exe_1", "jaos")]);
    act(() => useFake.setState({ solveSession: { status: "running", executionId: "exe_2" } }));
    act(() => useFake.setState({ solveSession: { status: "done", executionId: "exe_2" } }));

    await waitFor(() => expect(getProjectExecutions.mock.calls.length).toBeGreaterThanOrEqual(3));
    expect(await screen.findAllByRole("row")).toHaveLength(3);
  });
});
