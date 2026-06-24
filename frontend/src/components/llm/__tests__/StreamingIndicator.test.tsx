import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { StreamingIndicator } from "../StreamingIndicator";

describe("StreamingIndicator", () => {
  it("renders nothing when not streaming", () => {
    const { container } = render(
      <StreamingIndicator streaming={false} onStop={vi.fn()} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("shows default generating message when no statusCode is set", () => {
    render(<StreamingIndicator streaming={true} onStop={vi.fn()} />);
    // Unknown / missing code falls back to the generic "generating" i18n key.
    expect(screen.getByText("builder.llm.status.generating")).toBeInTheDocument();
  });

  it("resolves known status codes to i18n keys", () => {
    render(
      <StreamingIndicator
        streaming={true}
        onStop={vi.fn()}
        statusCode="generating_variables"
      />
    );
    expect(
      screen.getByText("builder.llm.status.generatingVariables")
    ).toBeInTheDocument();
  });

  it("falls back to generating for unknown status codes (forward-compat)", () => {
    render(
      <StreamingIndicator
        streaming={true}
        onStop={vi.fn()}
        statusCode="unknown_future_code"
      />
    );
    // Unknown codes must never render as raw strings — they resolve to
    // the generic "generating" fallback so no backend detail leaks.
    expect(screen.queryByText("unknown_future_code")).not.toBeInTheDocument();
    expect(screen.getByText("builder.llm.status.generating")).toBeInTheDocument();
  });

  it("calls onStop when stop button clicked", async () => {
    const onStop = vi.fn();
    render(<StreamingIndicator streaming={true} onStop={onStop} />);
    await userEvent.click(screen.getByText("builder.llm.streaming.stopGenerating"));
    expect(onStop).toHaveBeenCalledOnce();
  });
});
