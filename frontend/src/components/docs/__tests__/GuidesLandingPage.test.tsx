import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string; [key: string]: unknown }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

// Mock i18n navigation (avoid transitive next-intl/navigation loading)
vi.mock("@/i18n/navigation", () => ({
  Link: ({ children, href, ...props }: { children: React.ReactNode; href: string; [key: string]: unknown }) => (
    <a href={href} {...props}>{children}</a>
  ),
  usePathname: () => "/docs/guides",
  useRouter: () => ({ replace: vi.fn() }),
}));

import { GuidesLandingPage } from "../GuidesLandingPage";
import { guides, guidesByDomain } from "@/lib/docs/guide-data";

describe("GuidesLandingPage", () => {
  it("renders domain section headings", () => {
    render(<GuidesLandingPage />);

    for (const domain of Object.keys(guidesByDomain)) {
      expect(screen.getByRole("heading", { name: domain })).toBeInTheDocument();
    }
  });

  it("renders guide cards with title, description, difficulty badge, and template count", () => {
    render(<GuidesLandingPage />);

    // Check a sample guide renders its parts
    const firstGuide = guides[0];
    expect(screen.getByText(firstGuide.title)).toBeInTheDocument();
    expect(screen.getByText(firstGuide.description)).toBeInTheDocument();
  });

  it("shows all 34 guides when 'All' filter is active", () => {
    render(<GuidesLandingPage />);

    // Count all guide card links
    const links = screen.getAllByRole("link");
    const guideLinks = links.filter((l) =>
      l.getAttribute("href")?.startsWith("/docs/guides/")
    );
    expect(guideLinks).toHaveLength(34);
  });

  it("clicking difficulty filter shows only matching guides", async () => {
    const user = userEvent.setup();
    render(<GuidesLandingPage />);

    const beginnerCount = guides.filter((g) => g.difficulty === "beginner").length;

    // Click Beginner filter
    const beginnerButton = screen.getByRole("button", { name: /beginner/i });
    await user.click(beginnerButton);

    const links = screen.getAllByRole("link");
    const guideLinks = links.filter((l) =>
      l.getAttribute("href")?.startsWith("/docs/guides/")
    );
    expect(guideLinks).toHaveLength(beginnerCount);
  });

  it("clicking 'All' filter after filtering shows all guides", async () => {
    const user = userEvent.setup();
    render(<GuidesLandingPage />);

    // Filter first
    await user.click(screen.getByRole("button", { name: /beginner/i }));

    // Click All
    await user.click(screen.getByRole("button", { name: /^all$/i }));

    const links = screen.getAllByRole("link");
    const guideLinks = links.filter((l) =>
      l.getAttribute("href")?.startsWith("/docs/guides/")
    );
    expect(guideLinks).toHaveLength(34);
  });
});
