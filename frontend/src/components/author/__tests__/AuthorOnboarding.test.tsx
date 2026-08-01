/**
 * The checklist's step keys come from the server. next-intl does not throw on a
 * missing message — measured against 4.13, the default handler logs and returns
 * the key path — so a step the backend adds before the locales catch up would be
 * rendered at the reader as "author.onboarding.steps.<key>.title".
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";

import enMessages from "../../../../messages/en.json";

const { getAuthorOnboardingStatus } = vi.hoisted(() => ({
  getAuthorOnboardingStatus: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: { getAuthorOnboardingStatus } }));

vi.mock("@/i18n/navigation", () => ({
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

// The suite-wide next-intl mock answers `t.has` with a flat `true`, which would
// make every assertion below pass whatever the component does. This one resolves
// the key the way next-intl resolves it — walking the nesting, dot by dot —
// against the real English catalogue.
vi.mock("next-intl", () => ({
  useTranslations: (namespace: string) => {
    const lookup = (key: string): unknown =>
      `${namespace}.${key}`
        .split(".")
        .reduce<unknown>(
          (node, part) =>
            node && typeof node === "object"
              ? (node as Record<string, unknown>)[part]
              : undefined,
          enMessages,
        );
    const t = (key: string) => {
      const found = lookup(key);
      return typeof found === "string" ? found : `${namespace}.${key}`;
    };
    t.has = (key: string) => typeof lookup(key) === "string";
    return t;
  },
}));

import { AuthorOnboarding } from "../AuthorOnboarding";

const step = (key: string, completed = false) => ({
  key,
  completed,
  link: `/workspace/${key}`,
});

describe("AuthorOnboarding", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the steps the locales can name", async () => {
    getAuthorOnboardingStatus.mockResolvedValue({
      steps: [step("complete_profile"), step("publish_model"), step("add_rich_media")],
      all_complete: false,
    });

    render(<AuthorOnboarding />);

    expect(
      await screen.findByText("Complete your organization profile"),
    ).toBeInTheDocument();
    expect(screen.getByText("Publish your first model")).toBeInTheDocument();
    expect(screen.getByText("Add a logo or screenshots")).toBeInTheDocument();
  });

  it("skips a step the locales do not carry instead of printing its key", async () => {
    getAuthorOnboardingStatus.mockResolvedValue({
      steps: [step("complete_profile"), step("verify_your_domain")],
      all_complete: false,
    });

    render(<AuthorOnboarding />);

    expect(
      await screen.findByText("Complete your organization profile"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/author\.onboarding\.steps\./)).not.toBeInTheDocument();
  });

  it("renders no card at all when nothing on it can be named", async () => {
    getAuthorOnboardingStatus.mockResolvedValue({
      steps: [step("verify_your_domain"), step("connect_a_repository")],
      all_complete: false,
    });

    const { container } = render(<AuthorOnboarding />);

    await waitFor(() => {
      expect(getAuthorOnboardingStatus).toHaveBeenCalled();
    });
    expect(container).toBeEmptyDOMElement();
  });

  it("says nothing once every step is done", async () => {
    getAuthorOnboardingStatus.mockResolvedValue({
      steps: [step("complete_profile", true)],
      all_complete: true,
    });

    const { container } = render(<AuthorOnboarding />);

    await waitFor(() => {
      expect(getAuthorOnboardingStatus).toHaveBeenCalled();
    });
    expect(container).toBeEmptyDOMElement();
  });
});
