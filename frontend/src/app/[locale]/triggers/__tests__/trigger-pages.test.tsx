/**
 * The trigger pages, driven the way the QA pass drove them (2026-09-25).
 *
 * - The enable/disable toast passed the English words "enabled"/"disabled" into
 *   a translated sentence, so the Spanish page said "Trigger enabled".
 * - The detail page could not run a trigger once, and could not edit one,
 *   although the API had PATCH.
 *
 * The global next-intl mock returns "namespace.key", so a toast built from the
 * English state word shows up here as the old key, not the new one.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import React from "react";
import type { SolveTrigger } from "@/lib/types";

const { get, list, toggle, runNow, update, getSolvers, toast } = vi.hoisted(() => ({
  get: vi.fn(),
  list: vi.fn(),
  toggle: vi.fn(),
  runNow: vi.fn(),
  update: vi.fn(),
  getSolvers: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/api", () => ({
  api: {
    triggers: { get, list, toggle, runNow, update, delete: vi.fn() },
    getSolvers,
  },
  ApiError: class ApiError extends Error {},
}));
vi.mock("sonner", () => ({ toast }));
// The shared mock builds a new `t` on every render. These pages list `t` in a
// useCallback that loads the trigger, so a new `t` reloads it forever. One
// translator per namespace, kept, as next-intl does.
vi.mock("next-intl", () => {
  const cache = new Map<string, unknown>();
  const make = (namespace?: string) => {
    const t = (key: string) => (namespace ? `${namespace}.${key}` : key);
    return Object.assign(t, { rich: t, markup: t, raw: t, has: () => true });
  };
  return {
    useTranslations: (namespace?: string) => {
      const key = namespace ?? "";
      if (!cache.has(key)) cache.set(key, make(namespace));
      return cache.get(key);
    },
    useLocale: () => "en",
    useFormatter: () => ({ dateTime: (d: Date) => d.toISOString() }),
  };
});
vi.mock("next/navigation", () => ({
  useParams: () => ({ triggerId: "trg_1" }),
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/triggers/trg_1",
}));
vi.mock("@/contexts/AuthContext", () => ({ useAuth: () => ({ activeWorkspaceId: null }) }));
vi.mock("@/hooks/useWorkspacePermission", () => ({ useWorkspacePermission: () => true }));
vi.mock("@/components/workspaces/PermissionTooltip", () => ({
  useRoleDisplayName: () => "Editor",
}));
vi.mock("@/components/workspace/WorkspaceSwitchPrompt", () => ({
  useWorkspaceScopeGuard: () => ({
    showPrompt: false,
    targetWorkspaceName: null,
    handleAccept: vi.fn(),
    handleDecline: vi.fn(),
  }),
  WorkspaceSwitchPrompt: () => null,
}));
vi.mock("@/components/triggers/RunHistoryTable", () => ({ RunHistoryTable: () => null }));
vi.mock("@/components/triggers/ScheduleTab", () => ({ ScheduleTab: () => null }));
vi.mock("@/components/triggers/CodeSnippets", () => ({ CodeSnippets: () => null }));

import TriggerDetailPage from "../[triggerId]/page";
import TriggersPage from "../page";

const SOLVER_FIELD = {
  name: "solver",
  type: "string" as const,
  model_field_path: "solver_name",
  default: "jaos",
  required: false,
};

function trigger(overrides: Partial<SolveTrigger> = {}): SolveTrigger {
  return {
    id: "trg_1",
    organization_id: "org_1",
    created_by: "usr_1",
    name: "QA nightly diet",
    source: "project",
    document_id: null,
    version_id: null,
    model_project_id: "mp_1",
    model_project_version_id: "mpv_1",
    model_name: "Diet",
    override_schema: [SOLVER_FIELD],
    solver_name: null,
    webhook_url: "https://example.com/hook",
    is_enabled: true,
    total_runs: 0,
    trigger_secret_prefix: "abcd1234...",
    created_at: "2026-09-25T00:00:00Z",
    updated_at: "2026-09-25T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  getSolvers.mockResolvedValue({ solvers: [] });
});

describe("the enable/disable toast", () => {
  // CONTRACT-TEST: the toggle toast is a whole translated sentence per state
  it("says a whole sentence on the detail page", async () => {
    get.mockResolvedValue(trigger());
    toggle.mockResolvedValue(trigger({ is_enabled: false }));
    render(<TriggerDetailPage />);

    fireEvent.click(await screen.findByRole("button", { name: /triggers\.detail\.disable/ }));

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(toast.success).toHaveBeenCalledWith("triggers.detail.toggledOff");
  });

  it("says a whole sentence on the list page", async () => {
    list.mockResolvedValue([trigger({ is_enabled: false })]);
    toggle.mockResolvedValue(trigger({ is_enabled: true }));
    render(<TriggersPage />);

    fireEvent.click(await screen.findByTitle("triggers.list.enableTrigger"));

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(toast.success).toHaveBeenCalledWith("triggers.list.toggledOn");
  });
});

describe("Run now", () => {
  it("runs the trigger through the signed-in API, not the secret", async () => {
    get.mockResolvedValue(trigger());
    runNow.mockResolvedValue({ run_id: "trun_1", status: "pending" });
    render(<TriggerDetailPage />);

    fireEvent.click(await screen.findByRole("button", { name: /triggers\.detail\.runNow/ }));

    await waitFor(() => expect(runNow).toHaveBeenCalledWith("trg_1", undefined));
    expect(toast.success).toHaveBeenCalledWith("triggers.detail.runNowQueued");
  });

  it("is not offered on a disabled trigger", async () => {
    get.mockResolvedValue(trigger({ is_enabled: false }));
    render(<TriggerDetailPage />);

    expect(await screen.findByRole("button", { name: /triggers\.detail\.runNow/ })).toBeDisabled();
  });
});

describe("Edit", () => {
  it("saves the name, the solver and a changed default through PATCH", async () => {
    get.mockResolvedValue(trigger());
    update.mockResolvedValue(trigger({ name: "Renamed" }));
    render(<TriggerDetailPage />);

    fireEvent.click(await screen.findByRole("button", { name: /triggers\.detail\.edit/ }));
    fireEvent.change(screen.getByLabelText("triggers.detail.nameLabel"), {
      target: { value: "Renamed" },
    });
    fireEvent.change(screen.getByDisplayValue("jaos"), { target: { value: "scip" } });
    fireEvent.click(screen.getByRole("button", { name: "triggers.detail.save" }));

    await waitFor(() => expect(update).toHaveBeenCalled());
    expect(update).toHaveBeenCalledWith(
      "trg_1",
      {
        name: "Renamed",
        solver_name: null,
        override_schema: [{ ...SOLVER_FIELD, default: "scip" }],
      },
      undefined,
    );
    await waitFor(() => expect(screen.queryByTestId("trigger-edit-form")).toBeNull());
  });

  it("refuses a default that is not of the field's type, before any request", async () => {
    get.mockResolvedValue(
      trigger({
        override_schema: [
          { name: "cap", type: "number", model_field_path: "c", default: 4, required: false },
        ],
      }),
    );
    render(<TriggerDetailPage />);

    fireEvent.click(await screen.findByRole("button", { name: /triggers\.detail\.edit/ }));
    fireEvent.change(screen.getByDisplayValue("4"), { target: { value: "four" } });
    fireEvent.click(screen.getByRole("button", { name: "triggers.detail.save" }));

    expect(await screen.findByText("triggers.detail.invalidDefault")).toBeInTheDocument();
    expect(update).not.toHaveBeenCalled();
  });
});
