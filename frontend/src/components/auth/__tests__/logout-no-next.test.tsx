/**
 * # CONTRACT-TEST: signing out leads to a plain /login.
 *
 * Signing out cleared the session under a protected page, ProtectedRoute saw an
 * anonymous visitor and sent them to `/login?next=/workspace`. That URL stayed
 * in the browser, and the next person to sign in there landed on the last
 * user's page (QA, 2026-09-25). The real AuthProvider and ProtectedRoute run
 * together here, because the defect lived between the two.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { contextPush, routePush } = vi.hoisted(() => ({
  contextPush: vi.fn(),
  routePush: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: contextPush, replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/workspace",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ push: routePush }),
  usePathname: () => "/workspace",
}));

vi.mock("@/components/auth/EmailVerificationBanner", () => ({
  EmailVerificationBanner: () => null,
}));

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {
    status = 0;
  },
  api: {
    getMe: vi.fn().mockResolvedValue({
      user_id: "u1",
      user_name: "Olive Owner",
      user_email: "olive@example.com",
      organization_id: "o1",
      organization_name: "QA Team Org",
      is_admin: false,
      is_org_owner: true,
      can_build_plugins: false,
    }),
    logoutSession: vi.fn().mockResolvedValue(undefined),
    getApiKey: vi.fn().mockReturnValue(null),
    getWorkspace: vi.fn().mockRejectedValue(new Error("none")),
    listMembers: vi.fn().mockResolvedValue([]),
    listWorkspaces: vi.fn().mockResolvedValue({ items: [] }),
  },
}));

import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import { ProtectedRoute } from "../ProtectedRoute";

function Page() {
  const { logout } = useAuth();
  return <button onClick={() => logout()}>sign out</button>;
}

describe("signing out", () => {
  beforeEach(() => {
    contextPush.mockReset();
    routePush.mockReset();
    localStorage.clear();
  });

  it("goes to /login without the page the user was on", async () => {
    render(
      <AuthProvider>
        <ProtectedRoute>
          <Page />
        </ProtectedRoute>
      </AuthProvider>,
    );
    const button = await screen.findByRole("button", { name: "sign out" });

    await act(async () => {
      await userEvent.click(button);
    });

    await waitFor(() => expect(contextPush).toHaveBeenCalledWith("/login"));
    expect(routePush).not.toHaveBeenCalled();
  });
});
