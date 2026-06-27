import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import type { AdminOrganizationOverview } from "@/types/admin";

const { getOrganizationOverview, ApiError } = vi.hoisted(() => {
  class ApiError extends Error {
    status: number;
    detail?: string;
    constructor(status: number, message: string, detail?: string) {
      super(message);
      this.status = status;
      this.detail = detail;
    }
  }
  return { getOrganizationOverview: vi.fn(), ApiError };
});

vi.mock("@/lib/api", () => ({
  api: { admin: { getOrganizationOverview } },
  ApiError,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "org_1" }),
}));

vi.mock("@/i18n/navigation", () => ({
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

import OrganizationDetailPage from "../page";

const overview = (): AdminOrganizationOverview => ({
  organization: {
    id: "org_1",
    name: "Acme Inc",
    plan: "pro",
    credits_balance: 1000,
    credits_subscription: 500,
    credits_purchased: 300,
    credits_earned: 200,
    credits_used_month: 50,
    monthly_quota: 2000,
    rate_limit_per_minute: 120,
    rate_limit_per_day: 50000,
    ai_builder_enabled: true,
    byok_configured: false,
    max_private_plugins: 5,
    is_active: true,
    is_verified: false,
    is_public_profile: false,
    slug: null,
    billing_email: null,
    currency: "EUR",
    website_url: null,
    created_at: "2026-06-01T00:00:00Z",
    owner_user_id: "usr_1",
  },
  owner: { id: "usr_1", name: "Alice", email: "alice@acme.test" },
  counts: { users: 2, active_users: 2, api_keys: 1, active_api_keys: 1, models: 1, executions: 3 },
  execution_stats: { total: 3, completed: 2, failed: 1, running: 0, credits_consumed_total: 9 },
  users: [
    {
      id: "usr_1",
      organization_id: "org_1",
      name: "Alice",
      email: "alice@acme.test",
      is_admin: true,
      can_build_plugins: true,
      is_active: true,
      created_at: "2026-06-01T00:00:00Z",
    },
  ],
  api_keys: [
    {
      id: "apk_1",
      organization_id: "org_1",
      user_id: "usr_1",
      name: "CI Key",
      description: null,
      key_prefix: "ok_live_ab",
      is_active: true,
      created_at: "2026-06-02T00:00:00Z",
      last_used_at: null,
    },
  ],
  models: [
    {
      id: "om_1",
      display_name: "Routing Model",
      catalog_id: null,
      source: "custom",
      is_active: true,
      total_executions: 3,
      total_credits_used: 9,
      last_executed_at: null,
      created_at: "2026-06-03T00:00:00Z",
    },
  ],
  recent_executions: [
    {
      id: "exe_1",
      status: "completed",
      solver_name: "scip",
      credits_consumed: 3,
      execution_time_ms: 12,
      objective_value: 42,
      model_display_name: "Routing Model",
      executed_by_user_id: "usr_1",
      created_at: "2026-06-04T00:00:00Z",
    },
  ],
  recent_transactions: [
    {
      id: "ctx_1",
      transaction_type: "purchase",
      credits_amount: 100,
      balance_after: 1000,
      description: "Top-up",
      created_at: "2026-06-05T00:00:00Z",
    },
  ],
});

describe("OrganizationDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the org overview (header, KPIs, members, models, transactions)", async () => {
    getOrganizationOverview.mockResolvedValue(overview());

    render(<OrganizationDetailPage />);

    await waitFor(() => expect(screen.getByText("Acme Inc")).toBeInTheDocument());
    // a KPI label is rendered (translation mock echoes the namespaced key)
    expect(screen.getByText("admin.orgDetail.kpi.users")).toBeInTheDocument();
    // the org's member, model and transaction surface in their tables
    expect(screen.getAllByText("Alice").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Routing Model").length).toBeGreaterThan(0);
    expect(screen.getByText("Top-up")).toBeInTheDocument();
    // the API key is shown by prefix only, never a full secret
    expect(screen.getByText(/ok_live_ab/)).toBeInTheDocument();
  });

  it("shows the not-found state on a 404", async () => {
    getOrganizationOverview.mockRejectedValue(new ApiError(404, "not found"));

    render(<OrganizationDetailPage />);

    await waitFor(() =>
      expect(screen.getByText("admin.orgDetail.notFound")).toBeInTheDocument(),
    );
  });

  it("surfaces a load error with a working retry", async () => {
    getOrganizationOverview.mockRejectedValueOnce(new ApiError(500, "boom"));

    render(<OrganizationDetailPage />);

    await waitFor(() => expect(screen.getByText("boom")).toBeInTheDocument());

    getOrganizationOverview.mockResolvedValueOnce(overview());
    await userEvent.click(screen.getByRole("button", { name: "admin.orgDetail.retry" }));

    await waitFor(() => expect(screen.getByText("Acme Inc")).toBeInTheDocument());
    expect(getOrganizationOverview).toHaveBeenCalledTimes(2);
  });
});
