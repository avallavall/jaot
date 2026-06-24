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
