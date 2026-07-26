import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { AuthProvider, useAuth } from "../AuthContext";
import type { Plan, UserInfo } from "@/lib/types";

// Mock the api module. ApiError is a real class here because AuthContext uses
// `instanceof` on it to tell "your session is gone" apart from "the request
// happened to fail".
vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message = "failed") {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  },
  api: {
    login: vi.fn(),
    getMe: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: vi.fn(),
    clearApiKey: vi.fn(),
    getApiKey: vi.fn(),
  },
}));

import { api, ApiError } from "@/lib/api";

const mockMe: UserInfo = {
  user_id: "u1",
  user_name: "Test User",
  user_email: "test@example.com",
  organization_id: "o1",
  organization_name: "Test Org",
  plan: "free" as Plan,
  is_admin: false,
  can_build_plugins: false,
};

function TestConsumer() {
  const { user, isAuthenticated, isLoading, login, logout } = useAuth();
  return (
    <div>
      <span data-testid="loading">{isLoading ? "loading" : "ready"}</span>
      <span data-testid="auth">{isAuthenticated ? "authed" : "anon"}</span>
      <span data-testid="user">{user?.name ?? "none"}</span>
      <button onClick={() => login("ok_test_key")}>Login</button>
      <button onClick={logout}>Logout</button>
    </div>
  );
}

/** Minimal consumer for testing isOwner derivation (HEX-07 / D-7.1-06). */
function IsOwnerConsumer() {
  const { isOwner, isLoading } = useAuth();
  return (
    <div>
      <span data-testid="loading">{isLoading ? "loading" : "ready"}</span>
      <span data-testid="is-owner">{isOwner ? "owner" : "not-owner"}</span>
    </div>
  );
}

describe("AuthContext", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    vi.mocked(api.getApiKey).mockReturnValue(null);
  });

  it("starts unauthenticated when no key in localStorage", async () => {
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("loading").textContent).toBe("ready");
    });

    expect(screen.getByTestId("auth").textContent).toBe("anon");
    expect(screen.getByTestId("user").textContent).toBe("none");
  });

  it("login() calls api.login then api.getMe and sets user", async () => {
    vi.mocked(api.login).mockResolvedValue({
      success: true,
      user: { id: "u1", name: "Test User", email: "test@test.com", is_admin: false },
      organization: { id: "o1", name: "Org", plan: "free" as Plan },
      permissions: { can_build_plugins: false, can_publish: false, can_manage_keys: false },
    });
    vi.mocked(api.getMe).mockResolvedValue(mockMe);

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );

    await waitFor(() => expect(screen.getByTestId("loading").textContent).toBe("ready"));

    await act(async () => {
      await userEvent.click(screen.getByText("Login"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("auth").textContent).toBe("authed");
      expect(screen.getByTestId("user").textContent).toBe("Test User");
    });

    expect(api.login).toHaveBeenCalledWith("ok_test_key");
  });

  it("logout() clears user and redirects", async () => {
    localStorage.setItem("jaot_api_key", "ok_live_test");
    vi.mocked(api.getApiKey).mockReturnValue("ok_live_test");
    vi.mocked(api.getMe).mockResolvedValue(mockMe);

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );

    await waitFor(() => expect(screen.getByTestId("auth").textContent).toBe("authed"));

    await act(async () => {
      await userEvent.click(screen.getByText("Logout"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("auth").textContent).toBe("anon");
      expect(screen.getByTestId("user").textContent).toBe("none");
    });
  });

  it("auto-restores session from localStorage on mount", async () => {
    localStorage.setItem("jaot_api_key", "ok_persisted");
    vi.mocked(api.getApiKey).mockReturnValue("ok_persisted");
    vi.mocked(api.getMe).mockResolvedValue(mockMe);

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("auth").textContent).toBe("authed");
    });

    expect(api.getMe).toHaveBeenCalled();
  });

  // --- HEX-07 / D-7.1-06: isOwner derivation tests ---

  it("isOwner is false when /me returns is_admin=true, is_org_owner=false", async () => {
    localStorage.setItem("jaot_api_key", "ok_admin_non_owner");
    vi.mocked(api.getApiKey).mockReturnValue("ok_admin_non_owner");
    vi.mocked(api.getMe).mockResolvedValue({
      ...mockMe,
      is_admin: true,
      is_org_owner: false,
    });

    render(
      <AuthProvider>
        <IsOwnerConsumer />
      </AuthProvider>
    );

    await waitFor(() =>
      expect(screen.getByTestId("loading").textContent).toBe("ready"),
    );
    expect(screen.getByTestId("is-owner").textContent).toBe("not-owner");
  });

  it("isOwner is true when /me returns is_admin=true, is_org_owner=true", async () => {
    localStorage.setItem("jaot_api_key", "ok_owner");
    vi.mocked(api.getApiKey).mockReturnValue("ok_owner");
    vi.mocked(api.getMe).mockResolvedValue({
      ...mockMe,
      is_admin: true,
      is_org_owner: true,
    });

    render(
      <AuthProvider>
        <IsOwnerConsumer />
      </AuthProvider>
    );

    await waitFor(() =>
      expect(screen.getByTestId("loading").textContent).toBe("ready"),
    );
    expect(screen.getByTestId("is-owner").textContent).toBe("owner");
  });

  it("isOwner defaults to false when /me omits is_org_owner (old backend)", async () => {
    localStorage.setItem("jaot_api_key", "ok_old_backend");
    vi.mocked(api.getApiKey).mockReturnValue("ok_old_backend");
    // Simulate old backend that doesn't send is_org_owner by omitting the field
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { is_org_owner: _omit, ...meWithoutOrgOwner } = {
      ...mockMe,
      is_admin: true,
      is_org_owner: undefined as boolean | undefined,
    };
    vi.mocked(api.getMe).mockResolvedValue(meWithoutOrgOwner as UserInfo);

    render(
      <AuthProvider>
        <IsOwnerConsumer />
      </AuthProvider>
    );

    await waitFor(() =>
      expect(screen.getByTestId("loading").textContent).toBe("ready"),
    );
    // Safe fallback: missing is_org_owner → false, never silently grants access
    expect(screen.getByTestId("is-owner").textContent).toBe("not-owner");
  });

  // CONTRACT-TEST: only the server rejecting the credential ends the session.
  // Session validation used to funnel every failure into one catch that wiped
  // the stored key, so a 429 — which a user reaches just by navigating quickly,
  // since /auth/me runs on every page — logged them out mid-session.
  describe("session validation only ends on a real rejection", () => {
    it("recovers from a rate-limited /me instead of logging the user out", async () => {
      localStorage.setItem("jaot_api_key", "ok_throttled");
      vi.mocked(api.getApiKey).mockReturnValue("ok_throttled");
      vi.mocked(api.getMe)
        .mockRejectedValueOnce(new ApiError(429, "Too Many Requests"))
        .mockResolvedValueOnce({ ...mockMe, is_org_owner: true } as UserInfo);

      render(
        <AuthProvider>
          <TestConsumer />
        </AuthProvider>
      );

      await waitFor(
        () => expect(screen.getByTestId("loading").textContent).toBe("ready"),
        { timeout: 5000 },
      );
      expect(screen.getByTestId("auth").textContent).toBe("authed");
      expect(localStorage.getItem("jaot_api_key")).toBe("ok_throttled");
    });

    it("keeps the stored credential when /me keeps failing transiently", async () => {
      localStorage.setItem("jaot_api_key", "ok_server_down");
      vi.mocked(api.getApiKey).mockReturnValue("ok_server_down");
      vi.mocked(api.getMe).mockRejectedValue(new ApiError(503, "Service Unavailable"));

      render(
        <AuthProvider>
          <TestConsumer />
        </AuthProvider>
      );

      await waitFor(
        () => expect(screen.getByTestId("loading").textContent).toBe("ready"),
        { timeout: 5000 },
      );
      // Not signed in for this render, but the credential survives so the next
      // navigation can pick the session back up.
      expect(localStorage.getItem("jaot_api_key")).toBe("ok_server_down");
    });

    it("clears the credential when the server rejects it (401)", async () => {
      localStorage.setItem("jaot_api_key", "ok_revoked");
      vi.mocked(api.getApiKey).mockReturnValue("ok_revoked");
      vi.mocked(api.getMe).mockRejectedValue(new ApiError(401, "Unauthorized"));

      render(
        <AuthProvider>
          <TestConsumer />
        </AuthProvider>
      );

      await waitFor(() =>
        expect(screen.getByTestId("loading").textContent).toBe("ready"),
      );
      expect(screen.getByTestId("auth").textContent).toBe("anon");
      expect(localStorage.getItem("jaot_api_key")).toBeNull();
    });

    it("does not retry a rejected credential", async () => {
      localStorage.setItem("jaot_api_key", "ok_revoked_once");
      vi.mocked(api.getApiKey).mockReturnValue("ok_revoked_once");
      vi.mocked(api.getMe).mockRejectedValue(new ApiError(403, "Forbidden"));

      render(
        <AuthProvider>
          <TestConsumer />
        </AuthProvider>
      );

      await waitFor(() =>
        expect(screen.getByTestId("loading").textContent).toBe("ready"),
      );
      expect(vi.mocked(api.getMe)).toHaveBeenCalledTimes(1);
    });
  });
});
