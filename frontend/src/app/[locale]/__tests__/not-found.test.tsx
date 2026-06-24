import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import NotFound from "../not-found";

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

describe("[locale]/not-found (F-03)", () => {
  it("renders the branded 404 with localized copy", () => {
    render(<NotFound />);

    expect(screen.getByText("JAOT")).toBeInTheDocument();
    expect(screen.getByText("404")).toBeInTheDocument();
    // Global next-intl mock resolves t(key) to namespace.key
    expect(screen.getByText("errors.notFound.title")).toBeInTheDocument();
    expect(screen.getByText("errors.notFound.message")).toBeInTheDocument();
  });

  it("offers recovery links to home and marketplace", () => {
    render(<NotFound />);

    const home = screen.getByText("errors.notFound.backHome").closest("a");
    const marketplace = screen
      .getByText("errors.notFound.browseMarketplace")
      .closest("a");
    expect(home).toHaveAttribute("href", "/");
    expect(marketplace).toHaveAttribute("href", "/marketplace");
  });
});
