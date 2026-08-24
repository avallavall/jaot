import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

/**
 * ProtectedRoute is the ONLY place a missing session sends somebody to /login.
 * AuthProvider used to do it too, from a window event, and that reached the home
 * page, the marketplace and the docs — pages written for people with no account.
 * These tests hold both halves: the public pages are never touched, and a page
 * that does need a session still redirects, carrying where the visitor was.
 */
const { push, pathname, auth } = vi.hoisted(() => ({
  push: vi.fn(),
  pathname: { current: "/solve/executions" },
  auth: {
    current: {
      isAuthenticated: false,
      isLoading: false,
      user: null as { is_admin: boolean } | null,
      sessionEnded: false,
    },
  },
}));

vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => pathname.current,
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => auth.current,
}));

vi.mock("@/components/auth/EmailVerificationBanner", () => ({
  EmailVerificationBanner: () => null,
}));

import { ProtectedRoute } from "../ProtectedRoute";
import { EXPIRED_PARAM, RETURN_PARAM } from "@/lib/return-path";

function renderProtected(requireAdmin = false) {
  return render(
    <ProtectedRoute requireAdmin={requireAdmin}>
      <span data-testid="page">the page</span>
    </ProtectedRoute>
  );
}

describe("ProtectedRoute", () => {
  beforeEach(() => {
    pathname.current = "/solve/executions";
    auth.current = {
      isAuthenticated: false,
      isLoading: false,
      user: null,
      sessionEnded: false,
    };
  });

  it("sends an anonymous visitor to login with the page they asked for", () => {
    renderProtected();

    expect(push).toHaveBeenCalledWith(
      `/login?${RETURN_PARAM}=%2Fsolve%2Fexecutions`
    );
    expect(screen.queryByTestId("page")).toBeNull();
  });

  // Somebody who never signed in must not be told their session expired.
  it("does not claim a session expired when there never was one", () => {
    renderProtected();

    expect(push).toHaveBeenCalledWith(
      expect.not.stringContaining(EXPIRED_PARAM)
    );
  });

  it("says the session expired when one ran out under the user", () => {
    auth.current = { ...auth.current, sessionEnded: true };

    renderProtected();

    expect(push).toHaveBeenCalledWith(
      `/login?${RETURN_PARAM}=%2Fsolve%2Fexecutions&${EXPIRED_PARAM}=1`
    );
  });

  it("renders the page for a signed-in user and moves nobody", () => {
    auth.current = {
      isAuthenticated: true,
      isLoading: false,
      user: { is_admin: false },
      sessionEnded: false,
    };

    renderProtected();

    expect(screen.getByTestId("page")).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it("waits for the session check before deciding anything", () => {
    auth.current = { ...auth.current, isLoading: true };

    renderProtected();

    expect(push).not.toHaveBeenCalled();
    expect(screen.queryByTestId("page")).toBeNull();
  });
});
