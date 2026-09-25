/**
 * The admin's user action says what it does.
 *
 * "Delete" only sets is_active=false on the server (the same as unticking
 * "Active" in Edit), and the account can be turned back on. Its dialog said
 * "This action cannot be undone" (browser QA, 2026-09-24).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import enMessages from "../../../../../../messages/en.json";

const { getUsers, getOrganizations, request } = vi.hoisted(() => ({
  getUsers: vi.fn(),
  getOrganizations: vi.fn(),
  request: vi.fn(),
}));

vi.mock("next-intl", () => ({
  useTranslations: (ns: string) => {
    const t = (key: string, values?: Record<string, unknown>) =>
      `${ns}.${key}${values ? ` ${JSON.stringify(values)}` : ""}`;
    return Object.assign(t, { rich: t, has: () => true });
  },
  useLocale: () => "en",
}));

vi.mock("@/lib/api", () => ({
  api: { admin: { getUsers, getOrganizations }, request },
}));

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import UsersPage from "../page";

const ADA = {
  id: "usr_ada",
  name: "Ada",
  email: "ada@example.com",
  organization_id: "org_1",
  role: "member",
  is_active: true,
  created_at: "2026-09-01T10:00:00Z",
  last_login_at: null,
  updated_at: "2026-09-01T10:00:00Z",
};

describe("the admin's user action", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getOrganizations.mockResolvedValue({ items: [{ id: "org_1", name: "Org" }] });
    getUsers.mockResolvedValue({ items: [ADA], total: 1, pages: 1 });
    request.mockResolvedValue(undefined);
  });

  // CONTRACT-TEST: the admin user action is named for what the server does
  it("is called Deactivate and says the account can be turned back on", async () => {
    const user = userEvent.setup();
    render(<UsersPage />);

    await user.click(await screen.findByRole("button", { name: "admin.users.deactivate" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("admin.users.deactivateTitle")).toBeInTheDocument();
    expect(
      within(dialog).getByText('admin.users.deactivateConfirm {"name":"Ada"}'),
    ).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "admin.users.deactivate" }));

    await waitFor(() =>
      expect(request).toHaveBeenCalledWith("/api/v2/admin/users/usr_ada", { method: "DELETE" }),
    );
  });

  it("does not tell the admin in English that the action cannot be undone", () => {
    const users = (enMessages as { admin: { users: Record<string, unknown> } }).admin.users;
    expect(users.deactivate).toBe("Deactivate");
    expect(String(users.deactivateConfirm)).not.toMatch(/cannot be undone/i);
    expect(String(users.deactivateConfirm)).toMatch(/Edit/);
    expect(users).not.toHaveProperty("deleteConfirm");
  });
});
