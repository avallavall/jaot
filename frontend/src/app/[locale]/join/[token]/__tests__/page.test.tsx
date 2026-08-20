/**
 * The invite page, rendered.
 *
 * It had no render test at all: it unwraps `params` with React 19's `use()`, and
 * a plain `render()` leaves the Suspense fallback in the DOM for ever. Its
 * routing decision was covered where the helper lives (`lib/return-path.ts`) and
 * nothing asserted that this page calls it, or that a refusal prints one
 * sentence instead of two. `renderRoute` closes that.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { renderRoute, routeParams } from "@/test/route";
import { ApiError } from "@/lib/api";

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mockPush,
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => "/join/tok_abc",
  useSearchParams: () => new URLSearchParams(),
}));

const mockAcceptInvite = vi.fn();
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: { acceptInvite: (...args: unknown[]) => mockAcceptInvite(...args) },
  };
});

const auth = { isAuthenticated: true, isLoading: false };
vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => auth,
}));

vi.mock("sonner", () => ({ toast: { info: vi.fn(), error: vi.fn(), success: vi.fn() } }));

import JoinPage from "../page";

const render = () => renderRoute(<JoinPage params={routeParams({ token: "tok_abc" })} />);

describe("JoinPage", () => {
  beforeEach(() => {
    mockPush.mockClear();
    mockAcceptInvite.mockReset();
    auth.isAuthenticated = true;
    auth.isLoading = false;
  });

  it("accepts the invite and says so", async () => {
    mockAcceptInvite.mockResolvedValue({});
    await render();

    expect(mockAcceptInvite).toHaveBeenCalledWith("tok_abc");
    expect(screen.getByText("auth.join.successTitle")).toBeInTheDocument();
  });

  // CONTRACT-TEST: an anonymous visitor comes back to the invite after signing in
  it("sends an anonymous visitor to sign in, and back to this invite", async () => {
    auth.isAuthenticated = false;
    await render();

    expect(mockAcceptInvite).not.toHaveBeenCalled();
    expect(mockPush).toHaveBeenCalledWith("/login?next=%2Fjoin%2Ftok_abc");
  });

  it("waits while the session is still resolving", async () => {
    auth.isLoading = true;
    await render();

    expect(mockAcceptInvite).not.toHaveBeenCalled();
    expect(mockPush).not.toHaveBeenCalled();
  });

  // CONTRACT-TEST: a refused invite prints the server's reason, once
  it("prints the server's reason and not the generic one as well", async () => {
    mockAcceptInvite.mockRejectedValue(
      new ApiError(400, "Invite already used", undefined, "workspace.invite_used"),
    );
    await render();

    const message = await screen.findByTestId("join-error-message");
    expect(message).toHaveTextContent("errors.codes.workspace.invite_used");
    expect(screen.queryByText("auth.join.errorMessage")).not.toBeInTheDocument();
  });

  it("falls back to its own sentence when the refusal names no reason", async () => {
    mockAcceptInvite.mockRejectedValue(new Error("network down"));
    await render();

    const message = await screen.findByTestId("join-error-message");
    expect(message).toHaveTextContent("auth.join.acceptFailed");
  });
});
