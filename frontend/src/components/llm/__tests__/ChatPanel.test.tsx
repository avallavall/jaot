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

describe("ChatPanel — controlled mode (studio durable session)", () => {
  const controlled = [
    { id: "u1", role: "user" as const, content: "make x integer", formulation_json: null, created_at: new Date().toISOString() },
    { id: "a1", role: "assistant" as const, content: "Done — x is now integer", formulation_json: null, created_at: new Date().toISOString() },
  ];

  it("renders the parent-owned message list", () => {
    render(
      <ChatPanel
        initialMessages={[]}
        messages={controlled}
        onSend={vi.fn()}
        stream={makeStream()}
      />
    );
    expect(screen.getByText("make x integer")).toBeInTheDocument();
    expect(screen.getByText("Done — x is now integer")).toBeInTheDocument();
  });

  it("does NOT append a stream formulation to its own list (the parent owns it)", () => {
    const formulation = {
      summary: "extra assistant message that must NOT appear",
      variables: [{ name: "x", type: "integer" as const, lower_bound: 0, upper_bound: null, description: "" }],
      constraints: [],
      objective: { sense: "minimize" as const, expression: "x", description: "" },
      problem_name: "m",
    };
    render(
      <ChatPanel
        initialMessages={[]}
        messages={controlled}
        onSend={vi.fn()}
        stream={makeStream({ formulation })}
      />
    );
    // Only the two controlled messages render — the formulation did NOT add a third.
    expect(screen.getAllByTestId("chat-message")).toHaveLength(2);
    expect(screen.queryByText("extra assistant message that must NOT appear")).not.toBeInTheDocument();
  });
});
