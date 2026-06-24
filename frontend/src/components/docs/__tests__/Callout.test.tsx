import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Callout } from "../Callout";

describe("Callout", () => {
  it("renders children content", () => {
    render(<Callout>Test message</Callout>);
    expect(screen.getByText("Test message")).toBeInTheDocument();
  });

  it("defaults to info type", () => {
    const { container } = render(<Callout>Info message</Callout>);
    const callout = container.firstChild as HTMLElement;
    expect(callout.className).toContain("blue");
  });

  it("renders tip variant with green styling", () => {
    const { container } = render(<Callout type="tip">Tip message</Callout>);
    const callout = container.firstChild as HTMLElement;
    expect(callout.className).toContain("green");
  });

  it("renders warning variant with amber styling", () => {
    const { container } = render(
      <Callout type="warning">Warning message</Callout>
    );
    const callout = container.firstChild as HTMLElement;
    expect(callout.className).toContain("amber");
  });

  it("renders danger variant with red styling", () => {
    const { container } = render(
      <Callout type="danger">Danger message</Callout>
    );
    const callout = container.firstChild as HTMLElement;
    expect(callout.className).toContain("red");
  });

  it("renders info variant with blue styling", () => {
    const { container } = render(
      <Callout type="info">Info message</Callout>
    );
    const callout = container.firstChild as HTMLElement;
    expect(callout.className).toContain("blue");
  });

  it("renders an icon", () => {
    const { container } = render(<Callout type="tip">With icon</Callout>);
    const svg = container.querySelector("svg");
    expect(svg).toBeTruthy();
  });

  it("renders different icons for different types", () => {
    const { container: tipContainer } = render(
      <Callout type="tip">Tip</Callout>
    );
    const { container: warningContainer } = render(
      <Callout type="warning">Warning</Callout>
    );

    const tipIcon = tipContainer.querySelector("svg");
    const warningIcon = warningContainer.querySelector("svg");

    // Different lucide icons have different class names
    expect(tipIcon?.classList.toString()).not.toBe(
      warningIcon?.classList.toString()
    );
  });
});
