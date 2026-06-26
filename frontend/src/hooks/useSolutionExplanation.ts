"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BASE_URL, getApiKey, parseSSEEvents } from "@/hooks/useSSE";
import type { SSEEvent } from "@/lib/llm-types";
import {
  isLLMErrorCode,
  isLLMStatusCode,
  type LLMErrorCode,
  type LLMStatusCode,
} from "@/lib/llm-event-codes";

/** Body accepted by POST /llm/conversations/{id}/explain-solution. */
export interface ExplainSolutionBody {
  execution_id?: string;
  formulation?: Record<string, unknown> | null;
  solution?: Record<string, unknown> | null;
  sensitivity?: Record<string, unknown> | null;
  use_advanced_model?: boolean;
}

export interface SolutionExplanationState {
  /** Accumulated explanation text streamed from the model. */
  text: string;
  /** Whether the explanation stream is currently active. */
  streaming: boolean;
  /** Stable backend status code (e.g. "explaining"); map via resolveStatusKey. */
  statusCode: LLMStatusCode | null;
  /** Stable backend error code (null when no error); map via resolveErrorKey. */
  errorCode: LLMErrorCode | null;
  /** Request id echoed in status/error events; users cite it to support. */
  requestId: string | null;
  /** Start streaming an explanation for the given conversation + payload. */
  explain: (conversationId: string, body: ExplainSolutionBody) => Promise<void>;
  /** Cancel the current stream. */
  stop: () => void;
}

/**
 * POST-based SSE hook for the solution-explanation endpoint.
 *
 * Mirrors useFormulationStream's fetch + ReadableStream wiring but consumes only
 * the text-explanation event set (delta / status / error / done) — there is no
 * formulation/validation payload here. Pre-stream HTTP failures (402/403/429/5xx)
 * map to stable error codes so the UI never renders raw upstream detail.
 */
export function useSolutionExplanation(): SolutionExplanationState {
  const [text, setText] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [statusCode, setStatusCode] = useState<LLMStatusCode | null>(null);
  const [errorCode, setErrorCode] = useState<LLMErrorCode | null>(null);
  const [requestId, setRequestId] = useState<string | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);

  const stop = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setStreaming(false);
  }, []);

  const processEvents = useCallback((events: SSEEvent[]) => {
    for (const event of events) {
      switch (event.event) {
        case "delta": {
          try {
            const parsed = JSON.parse(event.data) as { text: string };
            setText((prev) => prev + parsed.text);
          } catch {
            setText((prev) => prev + event.data);
          }
          break;
        }
        case "status": {
          try {
            const parsed = JSON.parse(event.data) as { code?: string; request_id?: string };
            if (isLLMStatusCode(parsed.code)) {
              const code = parsed.code;
              setStatusCode((prev) => (prev === code ? prev : code));
            }
            if (parsed.request_id) {
              setRequestId((prev) => (prev === parsed.request_id ? prev : parsed.request_id!));
            }
          } catch {
            /* non-critical: status loss is acceptable */
          }
          break;
        }
        case "error": {
          try {
            const parsed = JSON.parse(event.data) as { code?: string; request_id?: string };
            setErrorCode(isLLMErrorCode(parsed.code) ? parsed.code : "internal_error");
            if (parsed.request_id) {
              setRequestId((prev) => (prev === parsed.request_id ? prev : parsed.request_id!));
            }
          } catch {
            setErrorCode("internal_error");
          }
          setStreaming(false);
          break;
        }
        case "done": {
          setStreaming(false);
          break;
        }
      }
    }
  }, []);

  const explain = useCallback(
    async (conversationId: string, body: ExplainSolutionBody) => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }

      setText("");
      setStatusCode(null);
      setErrorCode(null);
      setRequestId(null);
      setStreaming(true);

      const controller = new AbortController();
      abortControllerRef.current = controller;

      try {
        const apiKey = getApiKey();
        const headers: Record<string, string> = { "Content-Type": "application/json" };
        if (apiKey) {
          headers["Authorization"] = `Bearer ${apiKey}`;
        }

        const response = await fetch(
          `${BASE_URL}/api/v2/llm/conversations/${conversationId}/explain-solution`,
          {
            method: "POST",
            headers,
            body: JSON.stringify(body),
            signal: controller.signal,
          }
        );

        if (!response.ok) {
          setRequestId(response.headers.get("x-request-id"));
          if (response.status === 402) {
            setErrorCode("insufficient_credits");
          } else if (response.status === 429 || response.status >= 500) {
            setErrorCode("service_unavailable");
          } else {
            setErrorCode("internal_error");
          }
          setStreaming(false);
          return;
        }

        if (!response.body) {
          setErrorCode("internal_error");
          setStreaming(false);
          return;
        }

        const requestIdHeader = response.headers.get("x-request-id");
        if (requestIdHeader) {
          setRequestId(requestIdHeader);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            if (buffer.trim()) {
              processEvents(parseSSEEvents(buffer));
            }
            setStreaming(false);
            break;
          }
          buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

          const lastDoubleNewline = buffer.lastIndexOf("\n\n");
          if (lastDoubleNewline !== -1) {
            const complete = buffer.slice(0, lastDoubleNewline + 2);
            buffer = buffer.slice(lastDoubleNewline + 2);
            processEvents(parseSSEEvents(complete));
          }
        }
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === "AbortError") {
          return; // user cancelled
        }
        setErrorCode("service_unavailable");
        setStreaming(false);
      } finally {
        if (abortControllerRef.current === controller) {
          abortControllerRef.current = null;
        }
      }
    },
    [processEvents]
  );

  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  return { text, streaming, statusCode, errorCode, requestId, explain, stop };
}
