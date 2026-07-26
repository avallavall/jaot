"use client";

import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
} from "react";
import { useAdvancedModel } from "@/hooks/useAdvancedModel";
import { api } from "@/lib/api";
import { useExplanationStream } from "@/hooks/useExplanationStream";
import type { LLMErrorCode } from "@/lib/llm-event-codes";
import type { Conversation } from "@/lib/llm-types";

/**
 * The studio "Explain this model" session — lifted to the workspace provider so it
 * OUTLIVES the Analyze tab. The grounded SSE explanation stream and its conversation
 * live here, not inside the unmounting `ModelExplanationPanel`. This is the analogue
 * of the durable AI Assistant session (`StudioAssistantProvider`) and the durable
 * solve session (`useSolveSession`): switching Build/Analyze/Solve mid-explanation no
 * longer aborts the stream or wipes the produced text — returning to Analyze shows it
 * still streaming (or finished).
 *
 * Mounted above the tab panels (in `ModelProjectStoreProvider`, keyed by model), so
 * each model gets a fresh session and an in-flight explanation is per-model. It renders
 * `children` (a stable element) so its per-delta re-renders never reach the workspace
 * tree — only the `ModelExplanationPanel` consumer re-renders.
 */
export interface ModelExplanationSession {
  /** Accumulated explanation text streamed from the model. */
  text: string;
  /** Whether the explanation stream is currently active. */
  streaming: boolean;
  /** Stable backend error code (null when no error); map via resolveErrorKey. */
  errorCode: LLMErrorCode | null;
  /** Request id echoed in status/error events; users cite it to support. */
  requestId: string | null;
  /** True once the user has triggered an explanation at least once (controls the button label). */
  started: boolean;
  /** True when conversation setup (create) failed before the stream could start. */
  setupFailed: boolean;
  /** Create-or-reuse the conversation, then stream a fresh grounded explanation. */
  runExplain: () => void;
}

const ModelExplanationContext = createContext<ModelExplanationSession | null>(
  null,
);

/** Read the studio model-explanation session. Throws if used outside its provider. */
export function useModelExplanation(): ModelExplanationSession {
  const ctx = useContext(ModelExplanationContext);
  if (!ctx) {
    throw new Error(
      "useModelExplanation must be used within a ModelExplanationProvider",
    );
  }
  return ctx;
}

interface ModelExplanationProviderProps {
  /** The ModelProject id whose draft (HEAD) the backend explains. */
  projectId: string;
  children: React.ReactNode;
}

export function ModelExplanationProvider({
  projectId,
  children,
}: ModelExplanationProviderProps) {
  const stream = useExplanationStream();
  // Read from the shared external store, not local state: the toggle lives in the panel
  // while this provider is what sends, so two copies of the choice would drift.
  const [advancedModel] = useAdvancedModel();
  const conversationIdRef = useRef<string | null>(null);
  const [started, setStarted] = useState(false);
  const [setupFailed, setSetupFailed] = useState(false);

  const runExplain = useCallback(async () => {
    setSetupFailed(false);
    setStarted(true);
    try {
      // A short-lived conversation is created once per session and reused for every
      // regenerate, so each explanation streams into the same scoped conversation.
      if (!conversationIdRef.current) {
        const conv = await api.request<Conversation>(
          "/api/v2/llm/conversations",
          {
            method: "POST",
            body: JSON.stringify({}),
          },
        );
        conversationIdRef.current = conv.id;
      }
      await stream.explain(
        `/api/v2/llm/conversations/${conversationIdRef.current}/explain-model`,
        { project_id: projectId, use_advanced_model: advancedModel },
      );
    } catch {
      setSetupFailed(true);
    }
  }, [projectId, stream, advancedModel]);

  const value: ModelExplanationSession = {
    text: stream.text,
    streaming: stream.streaming,
    errorCode: stream.errorCode,
    requestId: stream.requestId,
    started,
    setupFailed,
    runExplain,
  };

  return (
    <ModelExplanationContext.Provider value={value}>
      {children}
    </ModelExplanationContext.Provider>
  );
}
