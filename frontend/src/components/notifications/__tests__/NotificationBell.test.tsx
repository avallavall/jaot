/**
 * The bell had no test at all, which is why it went unnoticed that it never
 * fetched anything for a browser login.
 *
 * It gated every call on a `jaot_api_key` in localStorage, but the web app
 * authenticates with HttpOnly cookies — that key is absent for every login
 * through the UI, so the guard returned early forever: no badge, no list, no
 * toast, however many notifications the API held. The first test below fails
 * against that version (localStorage is deliberately left empty), which is
 * exactly the production configuration it could not handle.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NotificationBell } from "@/components/notifications/NotificationBell";

const getNotifications = vi.fn();
const markAsRead = vi.fn();
const markAllAsRead = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    getNotifications: (...args: unknown[]) => getNotifications(...args),
    markAsRead: (...args: unknown[]) => markAsRead(...args),
    markAllAsRead: (...args: unknown[]) => markAllAsRead(...args),
  },
}));

const useAuthMock = vi.fn();
vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => useAuthMock(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const NOTIFICATION = {
  id: "ntf_1",
  type: "execution_completed",
  title: "Execution Completed",
  message: "Your optimization 'Plant mix' completed successfully. Objective value: 108.0000",
  is_read: false,
  created_at: new Date().toISOString(),
};

describe("NotificationBell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Production shape for a cookie session: nothing in localStorage at all.
    localStorage.clear();
    useAuthMock.mockReturnValue({ isAuthenticated: true, user: { id: "usr_1" }, isLoading: false });
    getNotifications.mockResolvedValue({ items: [NOTIFICATION], unread_count: 1 });
  });

  it("fetches and shows the unread badge for a cookie-authenticated user", async () => {
    render(<NotificationBell />);

    await waitFor(() => expect(getNotifications).toHaveBeenCalled());
    // The badge is the only place the count reaches the user's eye.
    expect(await screen.findByText("1")).toBeInTheDocument();
  });

  it("lists the notification when the bell is opened", async () => {
    render(<NotificationBell />);
    await waitFor(() => expect(getNotifications).toHaveBeenCalled());

    // The next-intl mock echoes "<namespace>.<key>", so match on the key path.
    await userEvent.click(screen.getByRole("button", { name: /notifications\.title/ }));

    expect(await screen.findByText("Execution Completed")).toBeInTheDocument();
    expect(screen.queryByText(/notifications\.noNotifications/)).not.toBeInTheDocument();
  });

  it("does not call the API when there is no session", async () => {
    useAuthMock.mockReturnValue({ isAuthenticated: false, user: null, isLoading: false });

    render(<NotificationBell />);

    await waitFor(() => expect(screen.getByRole("button")).toBeInTheDocument());
    expect(getNotifications).not.toHaveBeenCalled();
  });

  it("starts fetching once the session resolves after mount", async () => {
    // The auth context resolves asynchronously; a bell mounted before it lands
    // must still fetch when it arrives.
    useAuthMock.mockReturnValue({ isAuthenticated: false, user: null, isLoading: true });
    const { rerender } = render(<NotificationBell />);
    expect(getNotifications).not.toHaveBeenCalled();

    useAuthMock.mockReturnValue({ isAuthenticated: true, user: { id: "usr_1" }, isLoading: false });
    rerender(<NotificationBell />);

    await waitFor(() => expect(getNotifications).toHaveBeenCalled());
  });
});
