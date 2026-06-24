import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { Sidebar } from "../sidebar";
import type { CommunityStatus } from "@/lib/community";

// Mock community module
const mockFetchCommunityStatus = vi.fn<() => Promise<CommunityStatus>>();

vi.mock("@/lib/community", () => ({
  fetchCommunityStatus: (...args: unknown[]) => mockFetchCommunityStatus(...(args as [])),
  FEEDBACK_URL: "https://github.com/avallavall/jaot/issues/new/choose",
}));

// Mock next-intl
vi.mock("next-intl", () => ({
  useTranslations: () => {
    const t = (key: string) => key;
    t.rich = (key: string) => key;
    return t;
  },
}));

// Mock @/i18n/navigation (avoids ESM resolution issues with next-intl → next/navigation)
vi.mock("@/i18n/navigation", () => ({
  Link: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>{children}</a>
  ),
  usePathname: () => "/dashboard",
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
  }),
  redirect: vi.fn(),
  getPathname: vi.fn(),
}));

// Mock auth context
vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({
    logout: vi.fn(),
  }),
}));

// Mock guidance context
vi.mock("@/contexts/GuidanceContext", () => ({
  useGuidance: () => ({
    restartWizard: vi.fn(),
  }),
}));

// Mock child components that are not under test
vi.mock("@/components/notifications/NotificationBell", () => ({
  NotificationBell: () => <div data-testid="notification-bell" />,
}));

vi.mock("@/components/theme/ThemeToggle", () => ({
  ThemeToggle: () => <div data-testid="theme-toggle" />,
}));

vi.mock("@/components/layout/HelpMenu", () => ({
  HelpMenu: () => <div data-testid="help-menu" />,
}));

vi.mock("@/components/i18n/LanguageSwitcher", () => ({
  LanguageSwitcher: () => <div data-testid="language-switcher" />,
}));

vi.mock("@/components/tier/UsageIndicator", () => ({
  UsageIndicator: () => <div data-testid="usage-indicator" />,
}));

// NavItem structure matching what nav-items.tsx produces for community
const communityItems = [
  { label: "Dashboard", href: "/dashboard", icon: <span>D</span> },
  {
    label: "Community",
    href: "#community",
    icon: <span>C</span>,
    children: [
      { label: "Forum", href: "#discourse", icon: <span>F</span>, external: true },
      {
        label: "Feedback & Bug Reports",
        href: "https://github.com/avallavall/jaot/issues/new/choose",
        icon: <span>B</span>,
        external: true,
      },
    ],
  },
];

describe("Sidebar community integration", () => {
  beforeEach(() => {
    mockFetchCommunityStatus.mockReset();
  });

  it("renders Discourse SSO link when discourse_enabled is true", async () => {
    mockFetchCommunityStatus.mockResolvedValue({
      discourse_enabled: true,
      discourse_url: "https://forum.example.com",
    });

    render(<Sidebar items={communityItems} title="Test" />);

    // Wait for community status to load and Community section to appear
    await waitFor(() => {
      expect(screen.getByText("Community")).toBeInTheDocument();
    });

    // Expand the community section
    await userEvent.click(screen.getByText("Community"));

    // Check discourse link with SSO path
    const forumLink = screen.getByText("Forum").closest("a");
    expect(forumLink).toHaveAttribute("href", "https://forum.example.com/session/sso");
  });

  it("hides discourse link but keeps GitHub Issues when discourse disabled", async () => {
    mockFetchCommunityStatus.mockResolvedValue({
      discourse_enabled: false,
      discourse_url: null,
    });

    render(<Sidebar items={communityItems} title="Test" />);

    // Wait for the effect to settle (Dashboard should render)
    await waitFor(() => {
      expect(screen.getByText("Dashboard")).toBeInTheDocument();
    });

    // Community section should still be present (GitHub Issues link is always there)
    await waitFor(() => {
      expect(screen.getByText("Community")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByText("Community"));

    // Discourse link not present
    expect(screen.queryByText("Forum")).not.toBeInTheDocument();
    // GitHub Issues link present
    expect(screen.getByText("Feedback & Bug Reports")).toBeInTheDocument();
  });

  it("shows both Discourse and GitHub Issues when discourse enabled", async () => {
    mockFetchCommunityStatus.mockResolvedValue({
      discourse_enabled: true,
      discourse_url: "https://forum.example.com",
    });

    render(<Sidebar items={communityItems} title="Test" />);

    await waitFor(() => {
      expect(screen.getByText("Community")).toBeInTheDocument();
    });

    // Expand community
    await userEvent.click(screen.getByText("Community"));

    // Both links present
    expect(screen.getByText("Forum")).toBeInTheDocument();
    expect(screen.getByText("Feedback & Bug Reports")).toBeInTheDocument();
  });
});
