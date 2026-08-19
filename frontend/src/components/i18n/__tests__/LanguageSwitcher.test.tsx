import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LanguageSwitcher } from "../LanguageSwitcher";

// Mock next-intl useLocale
vi.mock("next-intl", () => ({
  useLocale: () => "en",
}));

// Mock i18n navigation (avoid transitive next-intl/navigation loading)
const mockReplace = vi.fn();
vi.mock("@/i18n/navigation", () => ({
  usePathname: () => "/marketplace",
  useRouter: () => ({
    replace: mockReplace,
  }),
}));

// Mock routing config
vi.mock("@/i18n/routing", () => ({
  routing: {
    locales: ["en", "es", "ca", "fr", "de"],
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
