import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import LoginPage from "../page";

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

  it("shows error message when email login fails", async () => {
    mockAuthState.loginWithEmail.mockRejectedValue(new Error("Invalid credentials"));
    render(<LoginPage />);

    await userEvent.type(screen.getByPlaceholderText("auth.login.emailPlaceholder"), "bad@example.com");
    await userEvent.type(screen.getByPlaceholderText("auth.login.passwordPlaceholder"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /auth\.login\.submit/i }));

    await waitFor(() => {
      expect(screen.getByText("Invalid credentials")).toBeInTheDocument();
    });
  });

  it("does not render form when already authenticated", () => {
    mockAuthState.isAuthenticated = true;
    mockAuthState.user = { is_admin: false };

    const { container } = render(<LoginPage />);
    expect(container.firstChild).toBeNull();
  });
});
