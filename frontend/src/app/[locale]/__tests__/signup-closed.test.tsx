/**
 * With registration closed, the sign-up page points at this site's contact
 * page.
 *
 * It said "Contact support@jaot.io if you need early access." A self-hosted
 * instance is not run by jaot.io, so the address sent people to somebody who
 * cannot open an account on it (browser QA, 2026-09-24).
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

import en from "../../../../messages/en.json";
import es from "../../../../messages/es.json";
import ca from "../../../../messages/ca.json";
import fr from "../../../../messages/fr.json";
import de from "../../../../messages/de.json";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("next-intl", () => {
  // `t.rich` calls the tag functions it is given, the way next-intl does, so a
  // link the page passes in actually renders.
  const t = Object.assign((key: string) => key, {
    rich: (key: string, tags: Record<string, (chunks: React.ReactNode) => React.ReactNode>) => (
      <>
        {key}
        {Object.entries(tags ?? {}).map(([name, render]) => (
          <React.Fragment key={name}>{render(`<${name}>`)}</React.Fragment>
        ))}
      </>
    ),
  });
  return { useTranslations: () => t, useLocale: () => "en" };
});

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ isAuthenticated: false, isLoading: false }),
}));

vi.mock("@/lib/api", () => ({
  api: { signupStatus: () => Promise.resolve({ enabled: false }) },
  ApiError: class ApiError extends Error {
    status = 0;
  },
}));

import SignupPage from "../signup/page";

describe("sign-up on an instance with registration closed", () => {
  it("links to the site's own contact page", async () => {
    render(<SignupPage />);

    expect(await screen.findByText("signup.registrationDisabled")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "<link>" })).toHaveAttribute("href", "/contact");
  });

  it("offers a way back to sign-in that is one link, not a button in a link", async () => {
    render(<SignupPage />);

    const back = await screen.findByRole("link", { name: "signup.backToLogin" });
    expect(back).toHaveAttribute("href", "/login");
    expect(back.querySelector("button")).toBeNull();
  });

  it("names no e-mail address in any language", () => {
    for (const messages of [en, es, ca, fr, de]) {
      const text = (messages as { auth: { signup: Record<string, string> } }).auth.signup
        .contactSupport;
      expect(text).not.toMatch(/@/);
      expect(text).toMatch(/<link>.+<\/link>/);
    }
  });
});
