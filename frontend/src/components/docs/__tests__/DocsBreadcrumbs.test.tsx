import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DocsBreadcrumbs } from "../DocsBreadcrumbs";

const mockUsePathname = vi.fn();

vi.mock("@/i18n/navigation", () => ({
  usePathname: () => mockUsePathname(),
  Link: ({ children, href, ...props }: { children: React.ReactNode; href: string; [key: string]: unknown }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

describe("DocsBreadcrumbs", () => {
  it("renders correct segments for a docs path", () => {
    mockUsePathname.mockReturnValue("/en/docs/api/authentication");
    render(<DocsBreadcrumbs />);

    expect(screen.getByText("Docs")).toBeInTheDocument();
    expect(screen.getByText("Api")).toBeInTheDocument();
    expect(screen.getByText("Authentication")).toBeInTheDocument();
  });

  it("renders getting-started path with spaces", () => {
    mockUsePathname.mockReturnValue("/en/docs/getting-started/introduction");
    render(<DocsBreadcrumbs />);

    expect(screen.getByText("Docs")).toBeInTheDocument();
    expect(screen.getByText("Getting Started")).toBeInTheDocument();
    expect(screen.getByText("Introduction")).toBeInTheDocument();
  });

  it("last segment is not a link", () => {
    mockUsePathname.mockReturnValue("/en/docs/api/authentication");
    render(<DocsBreadcrumbs />);

    const lastSegment = screen.getByText("Authentication");
    expect(lastSegment.tagName).not.toBe("A");
    expect(lastSegment.closest("a")).toBeNull();
  });

  it("non-last segments are links", () => {
    mockUsePathname.mockReturnValue("/en/docs/api/authentication");
    render(<DocsBreadcrumbs />);

    const docsLink = screen.getByText("Docs");
    expect(docsLink.closest("a")).not.toBeNull();
  });

  it("returns null for non-docs paths", () => {
    mockUsePathname.mockReturnValue("/en/marketplace");
    const { container } = render(<DocsBreadcrumbs />);
    expect(container.innerHTML).toBe("");
  });
});
