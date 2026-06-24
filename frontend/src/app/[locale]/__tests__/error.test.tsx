import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import LocaleError from "../error";

vi.mock("@/i18n/navigation", () => ({
  Link: ({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
    [key: string]: unknown;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

describe("[locale]/error (F-03)", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  it("renders the branded error page with localized copy and digest", () => {
    const error = Object.assign(new Error("boom"), { digest: "abc123" });
    render(<LocaleError error={error} reset={vi.fn()} />);

    expect(screen.getByText("JAOT")).toBeInTheDocument();
    expect(screen.getByText("errors.appError.title")).toBeInTheDocument();
    expect(screen.getByText("errors.appError.message")).toBeInTheDocument();
    // Digest line renders only when a digest exists (mock resolves to the key)
    expect(screen.getByText("errors.appError.digest")).toBeInTheDocument();
    // Never leak the raw error message to the UI
    expect(screen.queryByText(/boom/)).not.toBeInTheDocument();
  });

  it("omits the digest line when the error has no digest", () => {
    render(<LocaleError error={new Error("boom")} reset={vi.fn()} />);
    expect(screen.queryByText("errors.appError.digest")).not.toBeInTheDocument();
  });

  it("calls reset when Try again is clicked and links back home", () => {
    const reset = vi.fn();
    render(<LocaleError error={new Error("boom")} reset={reset} />);

    fireEvent.click(screen.getByText("errors.appError.retry"));
    expect(reset).toHaveBeenCalledTimes(1);

    const home = screen.getByText("errors.appError.backHome").closest("a");
    expect(home).toHaveAttribute("href", "/");
  });
});
