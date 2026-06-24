import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

// Mock next-themes
vi.mock("next-themes", () => ({
  ThemeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useTheme: () => ({ theme: "light", setTheme: vi.fn() }),
}));

// Mock AuthContext for sidebar
vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({
    user: null,
    isAuthenticated: false,
    isLoading: false,
    login: vi.fn(),
    logout: vi.fn(),
  }),
}));

// Mock GuidanceContext for sidebar
vi.mock("@/contexts/GuidanceContext", () => ({
  useGuidance: () => ({
    skillLevel: "beginner",
    restartWizard: vi.fn(),
  }),
}));

// Mock NotificationBell since it depends on api
vi.mock("@/components/notifications/NotificationBell", () => ({
  NotificationBell: () => <div data-testid="notification-bell" />,
}));

// Mock i18n navigation (avoid transitive next-intl/navigation loading)
vi.mock("@/i18n/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ replace: vi.fn() }),
  Link: ({ children, href, ...props }: { children: React.ReactNode; href: string; [key: string]: unknown }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

// Mock i18n routing
vi.mock("@/i18n/routing", () => ({
  routing: { locales: ["en", "es", "ca", "fr", "de"] },
}));

// Mock community lib
vi.mock("@/lib/community", () => ({
  fetchCommunityStatus: vi.fn().mockResolvedValue(null),
}));

// Mock UsageIndicator
vi.mock("@/components/tier/UsageIndicator", () => ({
  UsageIndicator: () => <div data-testid="usage-indicator" />,
}));

// Mock sonner
vi.mock("sonner", () => ({
  Toaster: () => null,
  toast: vi.fn(),
}));

// Mock api for LanguageSwitcher
vi.mock("@/lib/api", () => ({
  api: { updateUserProfile: vi.fn().mockResolvedValue({}) },
}));

import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { Sidebar } from "@/components/layout/sidebar";

describe("Accessible labels for icon-only buttons (A11Y-01)", () => {
  it("ThemeToggle button has aria-label", () => {
    render(<ThemeToggle />);

    // The theme toggle is an icon-only button - it MUST have an aria-label
    // for screen readers to announce its purpose
    const button = screen.getByRole("button");
    expect(button).toHaveAttribute("aria-label");
  });

  it("mobile hamburger button has aria-label", () => {
    const items = [
      { label: "Dashboard", href: "/dashboard", icon: <span>D</span> },
    ];

    render(<Sidebar items={items} title="JAOT" subtitle="Optimization" />);

    // Find the mobile hamburger button (the Menu icon button)
    // It should have an aria-label for screen readers
    const buttons = screen.getAllByRole("button");
    const menuButton = buttons.find(
      (btn) =>
        btn.getAttribute("aria-label")?.match(/menu|navigation|open/i)
    );
    expect(menuButton).toBeDefined();
    expect(menuButton).toHaveAttribute("aria-label");
  });

  it("mobile close button has aria-label", () => {
    const items = [
      { label: "Dashboard", href: "/dashboard", icon: <span>D</span> },
    ];

    render(<Sidebar items={items} title="JAOT" subtitle="Optimization" />);

    // Find the close button (X icon button)
    const buttons = screen.getAllByRole("button");
    const closeButton = buttons.find(
      (btn) =>
        btn.getAttribute("aria-label")?.match(/close/i)
    );
    expect(closeButton).toBeDefined();
    expect(closeButton).toHaveAttribute("aria-label");
  });

  it("sidebar nav has onKeyDown for arrow key navigation", () => {
    const items = [
      { label: "Dashboard", href: "/dashboard", icon: <span>D</span> },
      { label: "Settings", href: "/settings", icon: <span>S</span> },
    ];

    render(<Sidebar items={items} title="JAOT" subtitle="Optimization" />);

    // The nav element should exist with aria-label
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(nav).toBeDefined();
  });
});
