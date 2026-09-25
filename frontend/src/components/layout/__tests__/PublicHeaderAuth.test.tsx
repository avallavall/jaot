/**
 * The public header's account control is one link.
 *
 * "Sign In" was a <button> inside an <a>. Nested interactive elements are
 * invalid HTML: a screen reader announces two controls for one action, and
 * keyboard users tab through both (browser QA, 2026-09-24).
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const auth = { isAuthenticated: false, isLoading: false };

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => auth,
}));

import { PublicHeaderAuth } from "../PublicHeaderAuth";

describe("the public header's account control", () => {
  it("is a single link to sign in for a visitor", () => {
    auth.isAuthenticated = false;
    render(<PublicHeaderAuth />);

    const link = screen.getByRole("link", { name: "public.nav.signIn" });
    expect(link).toHaveAttribute("href", "/login");
    expect(link.querySelector("button")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("is a single link to the workspace for a signed-in user", () => {
    auth.isAuthenticated = true;
    render(<PublicHeaderAuth />);

    const link = screen.getByRole("link", { name: "public.nav.goToDashboard" });
    expect(link).toHaveAttribute("href", "/workspace");
    expect(link.querySelector("button")).toBeNull();
  });
});
