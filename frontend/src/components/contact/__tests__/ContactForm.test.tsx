/**
 * RED vitest stubs for ContactForm — Phase 9 Wave 0.
 *
 * Wave 1 lands `@/components/contact/ContactForm` and `@/contexts/AuthContext.useAuth`
 * is already in place. These tests currently fail at the import step with
 * "Cannot find module '@/components/contact/ContactForm'" — that is the
 * intended RED state.
 *
 * Implements Phase 9 decisions:
 *   D-05 (4 fields), D-06 (anonymous + signed-in prefill),
 *   D-08 (in-place thank-you swap + red banner + disabled button), D-09 (i18n keys locked).
 *
 * The 24 i18n key paths referenced below are LOCKED — Wave 1 must publish
 * these exact paths in every locale file (en, es, ca, fr, de). The next-intl
 * mock in src/test/setup.tsx echoes the key path back, so getByText("contact.success.title")
 * works without real translations available.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock the api client — Wave 1's ContactForm calls api.request("/api/v2/contact", ...).
vi.mock("@/lib/api", () => ({
  api: {
    request: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number;
    detail?: string;
    constructor(status: number, message: string, detail?: string) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.detail = detail;
    }
  },
}));

// Mock the auth context — useAuth() returns { user, isAuthenticated, ... }.
// Tests below override the mock implementation per test case.
vi.mock("@/contexts/AuthContext", () => ({
  useAuth: vi.fn(() => ({
    user: null,
    isAuthenticated: false,
    isLoading: false,
  })),
}));

// These imports DELIBERATELY reference a module that does not yet exist —
// Wave 1 lands `@/components/contact/ContactForm`. Until then, vitest fails
// the whole file with "Cannot find module", which IS the RED state.
import { ContactForm } from "@/components/contact/ContactForm";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

describe("ContactForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useAuth).mockReturnValue({
      user: null,
      isAuthenticated: false,
      isLoading: false,
    } as ReturnType<typeof useAuth>);
  });

  it("renders 4 visible fields + honeypot", () => {
    const { container } = render(<ContactForm />);

    // Visible fields.
    expect(container.querySelector('input[name="name"]')).toBeTruthy();
    expect(container.querySelector('input[name="email"]')).toBeTruthy();
    expect(container.querySelector('input[name="subject"]')).toBeTruthy();
    expect(container.querySelector('textarea[name="message"]')).toBeTruthy();

    // Hidden honeypot — display:none + tabindex=-1 (D-01).
    const honeypot = container.querySelector<HTMLInputElement>('input[name="website"]');
    expect(honeypot).not.toBeNull();
    expect(honeypot!.tabIndex).toBe(-1);
    // Either inline `style.display === "none"` or an equivalent class with computed style.
    const display = window.getComputedStyle(honeypot!).display;
    expect(display === "none" || honeypot!.style.display === "none").toBe(true);
  });

  it("prefills name and email from useAuth() session", () => {
    vi.mocked(useAuth).mockReturnValue({
      user: { id: "u1", name: "Alice Example", email: "alice@example.com" },
      isAuthenticated: true,
      isLoading: false,
    } as ReturnType<typeof useAuth>);

    const { container } = render(<ContactForm />);

    const nameInput = container.querySelector<HTMLInputElement>('input[name="name"]');
    const emailInput = container.querySelector<HTMLInputElement>('input[name="email"]');
    expect(nameInput?.value).toBe("Alice Example");
    expect(emailInput?.value).toBe("alice@example.com");

    // Both must remain editable — typing changes the value.
    expect(nameInput?.readOnly).toBeFalsy();
    expect(nameInput?.disabled).toBeFalsy();
    expect(emailInput?.readOnly).toBeFalsy();
    expect(emailInput?.disabled).toBeFalsy();
  });

  it("gracefully renders for anonymous (no useAuth session)", () => {
    vi.mocked(useAuth).mockReturnValue({
      user: null,
      isAuthenticated: false,
      isLoading: false,
    } as ReturnType<typeof useAuth>);

    const { container } = render(<ContactForm />);

    expect(container.querySelector<HTMLInputElement>('input[name="name"]')?.value).toBe("");
    expect(container.querySelector<HTMLInputElement>('input[name="email"]')?.value).toBe("");
    expect(container.querySelector<HTMLInputElement>('input[name="subject"]')?.value).toBe("");
    expect(
      container.querySelector<HTMLTextAreaElement>('textarea[name="message"]')?.value
    ).toBe("");
  });

  it("submits to POST /api/v2/contact and swaps to thank-you panel", async () => {
    vi.mocked(api.request).mockResolvedValueOnce({
      id: "ctc_test",
      status: "pending",
      created_at: "2026-05-16T12:00:00Z",
    });

    const user = userEvent.setup();
    render(<ContactForm />);

    await user.type(screen.getByRole("textbox", { name: /name/i }), "Alice");
    await user.type(screen.getByRole("textbox", { name: /email/i }), "alice@example.com");
    await user.type(screen.getByRole("textbox", { name: /subject/i }), "Hi");
    await user.type(screen.getByRole("textbox", { name: /message/i }), "Hello team");

    await act(async () => {
      await user.click(screen.getByRole("button", { name: /submit|contact\.form\.submit/i }));
    });

    await waitFor(() => {
      expect(api.request).toHaveBeenCalledTimes(1);
    });

    const callArgs = vi.mocked(api.request).mock.calls[0];
    expect(callArgs[0]).toBe("/api/v2/contact");
    expect((callArgs[1] as { method?: string }).method).toBe("POST");

    // Thank-you panel visible (D-08). Mock echoes "contact.success.title" verbatim.
    await waitFor(() => {
      expect(screen.getByText("contact.success.title")).toBeInTheDocument();
    });
  });

  it("shows red banner on 4xx and re-enables submit", async () => {
    vi.mocked(api.request).mockRejectedValueOnce(
      new ApiError(429, "Too Many Requests", "Rate limited")
    );

    const user = userEvent.setup();
    render(<ContactForm />);

    await user.type(screen.getByRole("textbox", { name: /name/i }), "Alice");
    await user.type(screen.getByRole("textbox", { name: /email/i }), "alice@example.com");
    await user.type(screen.getByRole("textbox", { name: /subject/i }), "Hi");
    await user.type(screen.getByRole("textbox", { name: /message/i }), "Hello team");

    const submitButton = screen.getByRole("button", {
      name: /submit|contact\.form\.submit/i,
    });
    await act(async () => {
      await user.click(submitButton);
    });

    await waitFor(() => {
      // Banner shows a translated copy — accept any of the locked error keys.
      const errorBanner =
        screen.queryByText(/contact\.error\.(generic|rateLimited|serverError)/i) ??
        screen.queryByRole("alert");
      expect(errorBanner).not.toBeNull();
    });

    // Submit button is no longer disabled after the failed in-flight resolves.
    await waitFor(() => {
      expect(
        (screen.getByRole("button", { name: /submit|contact\.form\.submit/i }) as HTMLButtonElement)
          .disabled
      ).toBe(false);
    });
  });

  it("submit button is disabled with spinner while in-flight", async () => {
    let resolveRequest: (value: unknown) => void = () => {};
    vi.mocked(api.request).mockImplementationOnce(
      () => new Promise((resolve) => {
        resolveRequest = resolve;
      })
    );

    const user = userEvent.setup();
    render(<ContactForm />);

    await user.type(screen.getByRole("textbox", { name: /name/i }), "Alice");
    await user.type(screen.getByRole("textbox", { name: /email/i }), "alice@example.com");
    await user.type(screen.getByRole("textbox", { name: /subject/i }), "Hi");
    await user.type(screen.getByRole("textbox", { name: /message/i }), "Hello team");

    await act(async () => {
      await user.click(
        screen.getByRole("button", { name: /submit|contact\.form\.submit/i })
      );
    });

    // During the deferred window: button disabled, spinner present.
    const submitBtn = screen.getByRole("button", {
      name: /submit|contact\.form\.submit|submitting/i,
    }) as HTMLButtonElement;
    expect(submitBtn.disabled).toBe(true);

    // Spinner — either role="status", aria-busy, or a class with "spin".
    const spinner =
      submitBtn.querySelector('[role="status"]') ??
      submitBtn.querySelector('[aria-busy="true"]') ??
      submitBtn.querySelector('[class*="spin"]');
    expect(spinner).not.toBeNull();

    // Cleanup — resolve the pending request so the test exits cleanly.
    await act(async () => {
      resolveRequest({ id: "ctc_x", status: "pending", created_at: "now" });
    });
  });
});
