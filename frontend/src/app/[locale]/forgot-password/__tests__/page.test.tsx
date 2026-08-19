import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

/**
 * Whether an address is registered must never leak, so a refusal that could
 * answer that question ends in the same neutral message. A refusal that says
 * nothing about the address is different: the page showed "you will receive a
 * link shortly" over a 429, and no mail was coming.
 */

const { forgotPassword, ApiError } = vi.hoisted(() => {
  class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  }
  return { forgotPassword: vi.fn(), ApiError };
});

vi.mock("@/lib/api", () => ({ api: { forgotPassword }, ApiError }));

vi.mock("@/i18n/navigation", () => ({
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

import ForgotPasswordPage from "../page";

async function ask() {
  render(<ForgotPasswordPage />);
  const email = screen.getByRole("textbox");
  await userEvent.type(email, "a@b.io");
  await userEvent.click(screen.getByRole("button", { name: /submit|send/i }));
}

describe("Forgot password", () => {
  beforeEach(() => vi.clearAllMocks());

  it("says a link is on its way when the server accepted the request", async () => {
    forgotPassword.mockResolvedValue({ success: true });

    await ask();

    await waitFor(() =>
      expect(screen.getByText("auth.forgotPassword.successMessage")).toBeInTheDocument(),
    );
  });

  it("says the same thing when the address is unknown, so nothing leaks", async () => {
    forgotPassword.mockRejectedValue(new ApiError(404, "not found"));

    await ask();

    await waitFor(() =>
      expect(screen.getByText("auth.forgotPassword.successMessage")).toBeInTheDocument(),
    );
  });

  it("admits it when the request was refused for asking too often", async () => {
    forgotPassword.mockRejectedValue(new ApiError(429, "rate limited"));

    await ask();

    await waitFor(() =>
      expect(screen.getByText("auth.forgotPassword.tooManyRequests")).toBeInTheDocument(),
    );
    expect(screen.queryByText("auth.forgotPassword.successMessage")).not.toBeInTheDocument();
  });

  it("admits it when the server broke", async () => {
    forgotPassword.mockRejectedValue(new ApiError(500, "boom"));

    await ask();

    await waitFor(() =>
      expect(screen.getByText("auth.forgotPassword.requestFailed")).toBeInTheDocument(),
    );
  });
});
