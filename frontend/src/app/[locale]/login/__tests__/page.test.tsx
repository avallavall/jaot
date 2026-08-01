import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import LoginPage from "../page";
import { ApiError } from "@/lib/api";

// Mutable state so individual tests can change isAuthenticated/isLoading
let mockAuthState = {
  login: vi.fn(),
  loginWithEmail: vi.fn(),
  isAuthenticated: false,
  isLoading: false,
  user: null as { is_admin: boolean } | null,
};

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => mockAuthState,
}));

const mockRouterPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockRouterPush }),
  usePathname: () => "/login",
}));

// Login routes through next-intl's navigation wrapper (bugfix B2) so the
// post-login redirect preserves the active locale. A separate spy lets the
// regression tests assert the push lands HERE and not on next/navigation.
const intlRouterPush = vi.fn();
vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ push: intlRouterPush }),
  Link: ({ children }: { children: React.ReactNode }) => <a>{children}</a>,
}));

describe("LoginPage", () => {
  beforeEach(() => {
    mockAuthState = {
      login: vi.fn(),
      loginWithEmail: vi.fn(),
      isAuthenticated: false,
      isLoading: false,
      user: null,
    };
    mockRouterPush.mockReset();
    intlRouterPush.mockReset();
  });

  it("renders the login form with email and password inputs only (no tabs)", () => {
    render(<LoginPage />);

    // Brand name rendered via translation key
    expect(screen.getByText("auth.login.brandName")).toBeInTheDocument();
    // Email and password inputs visible
    expect(screen.getByPlaceholderText("auth.login.emailPlaceholder")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("auth.login.passwordPlaceholder")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /auth\.login\.submit/i })).toBeInTheDocument();
    // No tab elements exist
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    // No API key input exists
    expect(screen.queryByPlaceholderText("auth.login.apiKeyPlaceholder")).not.toBeInTheDocument();
  });

  it("calls loginWithEmail() with entered credentials on submit", async () => {
    mockAuthState.loginWithEmail.mockResolvedValue(undefined);
    render(<LoginPage />);

    await userEvent.type(screen.getByPlaceholderText("auth.login.emailPlaceholder"), "test@example.com");
    await userEvent.type(screen.getByPlaceholderText("auth.login.passwordPlaceholder"), "password123");
    await userEvent.click(screen.getByRole("button", { name: /auth\.login\.submit/i }));

    await waitFor(() => {
      expect(mockAuthState.loginWithEmail).toHaveBeenCalledWith("test@example.com", "password123", false);
    });
  });

  // CONTRACT-TEST: the API's English `detail` must never surface on this screen.
  it("shows the translated fallback, not the API's English text, when login fails", async () => {
    mockAuthState.loginWithEmail.mockRejectedValue(
      new ApiError(401, "Invalid email or password", "Invalid email or password"),
    );
    render(<LoginPage />);

    await userEvent.type(screen.getByPlaceholderText("auth.login.emailPlaceholder"), "bad@example.com");
    await userEvent.type(screen.getByPlaceholderText("auth.login.passwordPlaceholder"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /auth\.login\.submit/i }));

    await waitFor(() => {
      expect(screen.getByText("auth.login.loginFailed")).toBeInTheDocument();
    });
    expect(screen.queryByText("Invalid email or password")).not.toBeInTheDocument();
  });

  it("renders the error code the server sent when there is one", async () => {
    mockAuthState.loginWithEmail.mockRejectedValue(
      new ApiError(
        423,
        "Account temporarily locked. Try again in 7 minutes.",
        "Account temporarily locked. Try again in 7 minutes.",
        "auth.account_locked",
        { minutes: 7 },
      ),
    );
    render(<LoginPage />);

    await userEvent.type(screen.getByPlaceholderText("auth.login.emailPlaceholder"), "bad@example.com");
    await userEvent.type(screen.getByPlaceholderText("auth.login.passwordPlaceholder"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /auth\.login\.submit/i }));

    await waitFor(() => {
      expect(screen.getByText("errors.codes.auth.account_locked")).toBeInTheDocument();
    });
  });

  it("does not render form when already authenticated", () => {
    mockAuthState.isAuthenticated = true;
    mockAuthState.user = { is_admin: false };

    const { container } = render(<LoginPage />);
    expect(container.firstChild).toBeNull();
  });

  // Bug B2: the redirect must go through next-intl's router so the locale chosen
  // on the public home survives into the dashboard. If LoginPage regressed to
  // next/navigation's useRouter, intlRouterPush would never be called.
  it("redirects an authenticated non-admin to /studio via next-intl router (B2)", () => {
    mockAuthState.isAuthenticated = true;
    mockAuthState.user = { is_admin: false };

    render(<LoginPage />);

    expect(intlRouterPush).toHaveBeenCalledWith("/studio");
  });

  it("redirects an authenticated admin to /admin via next-intl router (B2)", () => {
    mockAuthState.isAuthenticated = true;
    mockAuthState.user = { is_admin: true };

    render(<LoginPage />);

    expect(intlRouterPush).toHaveBeenCalledWith("/admin");
  });
});
