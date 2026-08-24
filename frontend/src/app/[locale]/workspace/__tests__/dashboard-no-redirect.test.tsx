import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";

/**
 * The dashboard used to ask /auth/me again and redirect to /login from a catch
 * that covered every failure. A 429 — which somebody reaches just by navigating
 * quickly, since /auth/me runs on every page load — threw a signed-in user off
 * their own dashboard. The session is AuthProvider's job, and this page already
 * sits behind ProtectedRoute.
 */
const { push, getAllExecutions, listTriggers, getUnreadCount } = vi.hoisted(() => ({
  push: vi.fn(),
  getAllExecutions: vi.fn(),
  listTriggers: vi.fn(),
  getUnreadCount: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/workspace",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    getAllExecutions: (...a: unknown[]) => getAllExecutions(...a),
    triggers: { list: (...a: unknown[]) => listTriggers(...a) },
    getUnreadCount: (...a: unknown[]) => getUnreadCount(...a),
  },
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({
    logout: vi.fn(),
    user: { id: "u1", name: "Test User", is_admin: false },
    organization: { id: "o1", name: "Test Org" },
  }),
}));

import DashboardPage from "../page";

describe("the dashboard when its figures fail to load", () => {
  beforeEach(() => {
    push.mockReset();
    getAllExecutions.mockReset();
    listTriggers.mockReset();
    getUnreadCount.mockReset();
  });

  it("stays put and still names the organisation", async () => {
    const throttled = Object.assign(new Error("Too Many Requests"), { status: 429 });
    getAllExecutions.mockRejectedValue(throttled);
    listTriggers.mockRejectedValue(throttled);
    getUnreadCount.mockRejectedValue(throttled);

    render(<DashboardPage />);

    await waitFor(() => expect(screen.getByText("Test Org")).toBeInTheDocument());
    expect(push).not.toHaveBeenCalled();
  });

  it("does not ask the server who the user is a second time", async () => {
    getAllExecutions.mockResolvedValue({ items: [] });
    listTriggers.mockResolvedValue([]);
    getUnreadCount.mockResolvedValue({ unread_count: 0 });

    render(<DashboardPage />);

    await waitFor(() => expect(screen.getByText("Test Org")).toBeInTheDocument());
    // api.getMe is not on the mock at all: calling it would throw.
    expect(push).not.toHaveBeenCalled();
  });
});
