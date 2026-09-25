import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LanguageSwitcher } from "../LanguageSwitcher";

// Mock next-intl. The translator prints the values it was given, so a test can
// see which language the button's name carries.
const { current } = vi.hoisted(() => ({ current: { locale: "en" } }));
vi.mock("next-intl", () => ({
  useLocale: () => current.locale,
  useTranslations: (namespace: string) => (key: string, values?: Record<string, unknown>) =>
    `${namespace}.${key}${values ? ` ${JSON.stringify(values)}` : ""}`,
}));

// Mock i18n navigation (avoid transitive next-intl/navigation loading)
const mockReplace = vi.fn();
vi.mock("@/i18n/navigation", () => ({
  getPathname: ({ href, locale }: { href: string; locale: string }) => `/${locale}${href}`,
  usePathname: () => "/marketplace",
  useRouter: () => ({
    replace: mockReplace,
  }),
}));

// Mock routing config
vi.mock("@/i18n/routing", () => ({
  routing: {
    locales: ["en", "es", "ca", "fr", "de"],
    defaultLocale: "en",
  },
}));

// Mock auth context
vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ isAuthenticated: false }),
}));

// Mock API
vi.mock("@/lib/api", () => ({
  api: { updateUserProfile: vi.fn().mockResolvedValue({}) },
}));

describe("LanguageSwitcher", () => {
  it("renders a trigger button with globe icon and current locale code", () => {
    render(<LanguageSwitcher />);
    const button = screen.getByRole("button");
    expect(button).toBeInTheDocument();
    expect(button.textContent).toContain("en");
  });

  // The button showed "EN" and nothing else, so a screen reader announced
  // "EN, button" with no word saying what the button does.
  it("names the button with what it is for and the current language", () => {
    render(<LanguageSwitcher />);
    const button = screen.getByRole("button");
    expect(button).toHaveAccessibleName(
      'common.languageSwitcher.label {"language":"English"}',
    );
  });

  it("shows all 5 languages when dropdown is opened", async () => {
    const user = userEvent.setup();
    render(<LanguageSwitcher />);
    await user.click(screen.getByRole("button"));

    // Check a sample of native-name languages appear
    expect(screen.getByText("English")).toBeInTheDocument();
    expect(screen.getByText("Deutsch")).toBeInTheDocument();
    expect(screen.getByText("Français")).toBeInTheDocument();

    // Count all menu items -- should be 5
    const items = screen.getAllByRole("menuitem");
    expect(items).toHaveLength(5);
  });

  it("calls router.replace with the selected locale to preserve current page", async () => {
    const user = userEvent.setup();
    render(<LanguageSwitcher />);
    await user.click(screen.getByRole("button"));
    await user.click(screen.getByText("Deutsch"));

    expect(mockReplace).toHaveBeenCalledWith("/marketplace", { locale: "de" });
  });

  it("fires onLocaleChange callback when a language is selected", async () => {
    const onLocaleChange = vi.fn();
    const user = userEvent.setup();
    render(<LanguageSwitcher onLocaleChange={onLocaleChange} />);
    await user.click(screen.getByRole("button"));
    await user.click(screen.getByText("Deutsch"));

    expect(onLocaleChange).toHaveBeenCalledWith("de");
  });
});

/**
 * `usePathname` gives the path and nothing else. Switching language on
 * /solve/executions/compare?a=exe_…&b=exe_… landed on the same page in the new
 * language with no query string, and the page said "Two execution IDs are
 * required. Add ?a={id}&b={id} to the URL." The comparison being read was gone.
 */
describe("LanguageSwitcher, what it keeps", () => {
  async function pickSpanish() {
    const user = userEvent.setup();
    render(<LanguageSwitcher />);
    await user.click(screen.getByRole("button"));
    await user.click(screen.getByText("Español"));
  }

  // CONTRACT-TEST: switching language keeps the page you were on, whole
  it("carries the query string across", async () => {
    mockReplace.mockClear();
    window.history.replaceState({}, "", "/marketplace?a=exe_1&b=exe_2");

    await pickSpanish();

    expect(mockReplace).toHaveBeenCalledWith("/marketplace?a=exe_1&b=exe_2", { locale: "es" });
  });

  it("carries the hash across too", async () => {
    mockReplace.mockClear();
    window.history.replaceState({}, "", "/marketplace?tab=data#results");

    await pickSpanish();

    expect(mockReplace).toHaveBeenCalledWith("/marketplace?tab=data#results", { locale: "es" });
  });

  it("passes the bare path when there is nothing else on the address", async () => {
    mockReplace.mockClear();
    window.history.replaceState({}, "", "/marketplace");

    await pickSpanish();

    expect(mockReplace).toHaveBeenCalledWith("/marketplace", { locale: "es" });
  });
});

/**
 * Found driving the site (2026-09-25): on /de, picking English set the cookie,
 * then the client router reused its cached "/" -> "/de" redirect and the page
 * stayed German. Switching to the default language loads "/en/..." instead.
 */
describe("LanguageSwitcher, back to the default language", () => {
  it("loads the page through the /en prefix, keeping query and hash", async () => {
    current.locale = "de";
    mockReplace.mockClear();
    window.history.replaceState({}, "", "/de/marketplace?a=1#top");
    const assign = vi.fn();
    const original = window.location;
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...original, assign, search: "?a=1", hash: "#top" },
    });
    try {
      const user = userEvent.setup();
      render(<LanguageSwitcher />);
      await user.click(screen.getByRole("button"));
      await user.click(screen.getByText("English"));
      expect(assign).toHaveBeenCalledWith("/en/marketplace?a=1#top");
      expect(mockReplace).not.toHaveBeenCalled();
    } finally {
      Object.defineProperty(window, "location", { configurable: true, value: original });
      current.locale = "en";
    }
  });
});
