import React, { useState } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

// The lifted explanation stream is mocked at the hook boundary: a stable object whose
// `explain` we can assert was called. The point of the provider is that IT (and this
// hook) stay mounted above the tabs, so the session survives a consumer unmount.
const { mockExplain, mockRequest } = vi.hoisted(() => ({
  mockExplain: vi.fn().mockResolvedValue(undefined),
  mockRequest: vi.fn().mockResolvedValue({ id: "conv_1" }),
}));

vi.mock("@/hooks/useExplanationStream", () => ({
  useExplanationStream: () => ({
    text: "",
    streaming: false,
    statusCode: null,
    errorCode: null,
    requestId: null,
    explain: mockExplain,
    stop: vi.fn(),
    reset: vi.fn(),
  }),
}));

vi.mock("@/lib/api", () => ({ api: { request: mockRequest } }));

import {
  ModelExplanationProvider,
  useModelExplanation,
} from "../ModelExplanationProvider";

/** Minimal consumer: shows `started` + can trigger an explanation. */
function ExplainConsumer() {
  const { started, runExplain } = useModelExplanation();
  return (
    <div>
      <span data-testid="started">{started ? "started" : "idle"}</span>
      <button onClick={runExplain}>run</button>
    </div>
  );
}

/** A harness that mounts/unmounts the consumer under a STABLE provider (≈ tab switch). */
function Harness() {
  const [show, setShow] = useState(true);
  return (
    <ModelExplanationProvider projectId="mp_1">
      <button onClick={() => setShow((s) => !s)}>toggle</button>
      {show && <ExplainConsumer />}
    </ModelExplanationProvider>
  );
}

describe("ModelExplanationProvider — durable explain session", () => {
  beforeEach(() => vi.clearAllMocks());

  it("throws when the session is read outside its provider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<ExplainConsumer />)).toThrow(
      /useModelExplanation must be used within a ModelExplanationProvider/
    );
    spy.mockRestore();
  });

  it("keeps the started session when the consumer unmounts and remounts (tab switch)", async () => {
    render(<Harness />);
    expect(screen.getByTestId("started").textContent).toBe("idle");

    // Trigger an explanation: creates the conversation then starts the stream.
    fireEvent.click(screen.getByText("run"));
    await waitFor(() => expect(screen.getByTestId("started").textContent).toBe("started"));
    expect(mockExplain).toHaveBeenCalledWith(
      "/api/v2/llm/conversations/conv_1/explain-model",
      { project_id: "mp_1" }
    );

    // Leave the tab (unmount the panel) and come back (remount) — provider stays mounted.
    fireEvent.click(screen.getByText("toggle"));
    expect(screen.queryByTestId("started")).toBeNull();
    fireEvent.click(screen.getByText("toggle"));

    // The session survived: still "started", with NO second conversation created.
    expect(screen.getByTestId("started").textContent).toBe("started");
    expect(mockRequest).toHaveBeenCalledTimes(1);
  });
});
