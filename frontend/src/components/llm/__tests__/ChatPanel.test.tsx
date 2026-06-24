import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

// jsdom doesn't implement scrollIntoView
beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

// Mock child components to isolate ChatPanel behavior
vi.mock("../ChatMessage", () => ({
  ChatMessage: ({ message }: { message: { content: string } }) => (
    <div data-testid="chat-message">{message.content}</div>
  ),
}));
vi.mock("../ExamplePrompts", () => ({
  ExamplePrompts: () => <div data-testid="example-prompts" />,
}));
vi.mock("../StreamingIndicator", () => ({
  StreamingIndicator: ({ statusCode }: { statusCode?: string | null }) => (
    statusCode ? <div data-testid="status-code">{statusCode}</div> : null
  ),
}));

import { ChatPanel } from "../ChatPanel";
import type { FormulationStreamState } from "@/hooks/useSSE";

function makeStream(overrides: Partial<FormulationStreamState> = {}): FormulationStreamState {
  return {
    chunks: [],
    rawText: "",
    formulation: null,
    validationErrors: [],
    streaming: false,
    errorCode: null,
    statusCode: null,
    requestId: null,
    partialWarning: null,
    sendMessage: vi.fn(),
    stopGenerating: vi.fn(),
    ...overrides,
  };
}

describe("ChatPanel — partialWarning (LLM-16)", () => {
  const baseMessages = [
    { id: "msg1", role: "user" as const, content: "Solve my problem", formulation_json: null, created_at: new Date().toISOString() },
  ];

  it("does NOT show warning banner when partialWarning is null", () => {
    render(
      <ChatPanel
        initialMessages={baseMessages}
        stream={makeStream()}
        onFormulationReady={vi.fn()}
      />
    );
    expect(screen.queryByText("builder.llm.chat.partialResult")).not.toBeInTheDocument();
  });

  it("shows warning banner when partialWarning is set and streaming is false", () => {
    render(
      <ChatPanel
        initialMessages={baseMessages}
        stream={makeStream({ partialWarning: "Could not generate constraints. Only variables included." })}
        onFormulationReady={vi.fn()}
      />
    );
    expect(screen.getByText("builder.llm.chat.partialResult")).toBeInTheDocument();
    expect(screen.getByText("Could not generate constraints. Only variables included.")).toBeInTheDocument();
  });

  it("does NOT show warning banner while still streaming", () => {
    render(
      <ChatPanel
        initialMessages={baseMessages}
        stream={makeStream({ partialWarning: "Partial...", streaming: true })}
        onFormulationReady={vi.fn()}
      />
    );
    expect(screen.queryByText("builder.llm.chat.partialResult")).not.toBeInTheDocument();
  });
});
