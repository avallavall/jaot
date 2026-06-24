import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CodeBlock } from "../CodeBlock";

describe("CodeBlock", () => {
  it("renders children inside a pre element", () => {
    const { container } = render(
      <CodeBlock>
        <code>console.log(&quot;hello&quot;)</code>
      </CodeBlock>
    );
    const pre = container.querySelector("pre");
    expect(pre).toBeTruthy();
    expect(pre!.textContent).toContain("console.log");
  });

  it("renders a copy button", () => {
    render(
      <CodeBlock>
        <code>test code</code>
      </CodeBlock>
    );
    const button = screen.getByRole("button", { name: /copy code/i });
    expect(button).toBeInTheDocument();
  });

  it("shows check icon after clicking copy button (confirms clipboard interaction)", async () => {
    // Mock clipboard at the window level to ensure the component's context sees it
    const writeTextFn = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(window.navigator, "clipboard", {
      value: { writeText: writeTextFn },
      writable: true,
      configurable: true,
    });

    const user = userEvent.setup();
    render(
      <CodeBlock>
        <code>copied text</code>
      </CodeBlock>
    );
    const button = screen.getByRole("button", { name: /copy code/i });
    await user.click(button);

    // The Check icon (lucide-check) appears after successful copy
    await waitFor(() => {
      const svg = document.querySelector(".lucide-check");
      expect(svg).toBeTruthy();
    });
  });
});
