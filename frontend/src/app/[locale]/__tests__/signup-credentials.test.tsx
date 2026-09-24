/**
 * # CONTRACT-TEST: signing up must not leave a credential on the machine.
 *
 * The signup response carries an account API key, and the page used to write it
 * into localStorage. That left a live, non-expiring Bearer credential on the
 * browser of everyone who ever signed up, and `api.ts` then sent it as the
 * Authorization header on every request from that browser — while every other
 * session in the product runs on cookies, which is the decision written into
 * AuthContext's email-login path ("Cookie-based session — no API key in
 * localStorage").
 *
 * The user is never shown that key either. Keys for programmatic use are minted,
 * and revealed once, on /workspace/api-keys.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const push = vi.fn();
const loginWithEmail = vi.fn().mockResolvedValue(undefined);
const signupWithEmail = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("next-intl", () => {
  // The page uses both `t(key)` and `t.rich(key, {...})`, so the stub has to be
  // a function carrying a `rich` of its own.
  const t = Object.assign((key: string) => key, { rich: (key: string) => key });
  return { useTranslations: () => t, useLocale: () => "en" };
});

vi.mock("next/link", () => ({
  default: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ loginWithEmail }),
}));

vi.mock("@/lib/api", () => ({
  api: {
    signupWithEmail: (...args: unknown[]) => signupWithEmail(...args),
    // The page asks whether this instance takes accounts before drawing the form.
    signupStatus: () => Promise.resolve({ enabled: true }),
  },
  ApiError: class ApiError extends Error {
    status = 0;
  },
}));

import SignupPage from "../signup/page";

async function fillAndSubmit() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("signup.emailLabel"), "new@example.com");
  await user.type(screen.getByLabelText("signup.nameLabel"), "New Person");
  await user.type(screen.getByLabelText("signup.orgLabel"), "New Org");
  await user.type(screen.getByLabelText("signup.passwordLabel"), "AveryStr0ng!Pass");
  await user.type(screen.getByLabelText("signup.confirmPasswordLabel"), "AveryStr0ng!Pass");
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: /signup/i }));
}

describe("signing up", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    signupWithEmail.mockResolvedValue({
      api_key: "ok_live_thisisalivecredential",
      user: { id: "usr_1" },
    });
  });

  it("does not write the account API key into localStorage", async () => {
    render(<SignupPage />);

    await fillAndSubmit();

    await waitFor(() => expect(signupWithEmail).toHaveBeenCalled());
    expect(localStorage.getItem("jaot_api_key")).toBeNull();
    // Nothing else may smuggle it in either.
    const stored = Object.keys(localStorage).map((k) => localStorage.getItem(k) ?? "");
    expect(stored.some((v) => v.includes("ok_live_"))).toBe(false);
  });

  it("still establishes the cookie session and lands in the studio", async () => {
    render(<SignupPage />);

    await fillAndSubmit();

    await waitFor(() => expect(loginWithEmail).toHaveBeenCalledWith("new@example.com", "AveryStr0ng!Pass"));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/studio"));
  });
});

describe("the terms box", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // The button used to be disabled until the box was ticked. It said nothing
  // about why, and this message could never appear (found driving the page,
  // 2026-09-24).
  it("says why the account was not created when the box is left unticked", async () => {
    const user = userEvent.setup();
    render(<SignupPage />);

    await user.type(await screen.findByLabelText("signup.emailLabel"), "new@example.com");
    await user.type(screen.getByLabelText("signup.nameLabel"), "New Person");
    await user.type(screen.getByLabelText("signup.orgLabel"), "New Org");
    await user.type(screen.getByLabelText("signup.passwordLabel"), "AveryStr0ng!Pass");
    await user.type(screen.getByLabelText("signup.confirmPasswordLabel"), "AveryStr0ng!Pass");
    const submit = screen.getByRole("button", { name: /signup/i });
    expect(submit).toBeEnabled();
    await user.click(submit);

    expect(await screen.findByText("signup.tosRequired")).toBeInTheDocument();
    expect(signupWithEmail).not.toHaveBeenCalled();
  });
});
