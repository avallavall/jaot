/**
 * # CONTRACT-TEST: signing up from an invite joins the team that sent it.
 *
 * Signup opened a new organization every time, and accepting an invite refuses
 * an account of another organization, so an invited person with no account
 * could never join (QA, 2026-09-25). The page now carries the invite token
 * through signup: no organization is asked for, and the account lands in the
 * workspace it joined.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const push = vi.fn();
const loginWithEmail = vi.fn().mockResolvedValue(undefined);
const signupWithEmail = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("next-intl", () => {
  const t = Object.assign((key: string) => key, {
    rich: (key: string) => key,
    has: () => true,
  });
  return { useTranslations: () => t, useLocale: () => "en" };
});

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ loginWithEmail }),
}));

vi.mock("@/lib/api", () => ({
  api: {
    signupWithEmail: (...args: unknown[]) => signupWithEmail(...args),
    signupStatus: () => Promise.resolve({ enabled: true }),
  },
  ApiError: class ApiError extends Error {
    status = 0;
  },
}));

import SignupPage from "../signup/page";

async function fillAndSubmit() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("signup.emailLabel"), "max@example.com");
  await user.type(screen.getByLabelText("signup.nameLabel"), "Max Member");
  await user.type(screen.getByLabelText("signup.passwordLabel"), "AveryStr0ng!Pass");
  await user.type(screen.getByLabelText("signup.confirmPasswordLabel"), "AveryStr0ng!Pass");
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: /signup/i }));
}

describe("signing up from an invite", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signupWithEmail.mockResolvedValue({
      api_key: "ok_live_x",
      organization_id: "org_team",
      joined_workspace_id: "wks_team",
    });
  });

  afterEach(() => {
    window.history.pushState({}, "", "/");
  });

  it.each([
    ["the invite page's link", "/signup?invite=tok_abc"],
    ["the login page's sign-up link", "/signup?next=%2Fjoin%2Ftok_abc"],
  ])("sends the invite and asks for no organization, from %s", async (_from, url) => {
    window.history.pushState({}, "", url);
    render(<SignupPage />);

    expect(await screen.findByTestId("signup-invite-notice")).toBeInTheDocument();
    expect(screen.queryByLabelText("signup.orgLabel")).toBeNull();

    await fillAndSubmit();

    await waitFor(() => expect(signupWithEmail).toHaveBeenCalled());
    const body = signupWithEmail.mock.calls[0][0];
    expect(body.invite_token).toBe("tok_abc");
    expect(body).not.toHaveProperty("organization_name");
    expect(push).toHaveBeenCalledWith("/workspace/workspaces/wks_team");
  });

  it("still asks for an organization without an invite", async () => {
    render(<SignupPage />);

    expect(await screen.findByLabelText("signup.orgLabel")).toBeInTheDocument();
    expect(screen.queryByTestId("signup-invite-notice")).toBeNull();
  });
});
