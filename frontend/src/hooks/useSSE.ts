"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Formulation, ValidationError, SSEEvent } from "@/lib/llm-types";
import {
  isLLMErrorCode,
  isLLMStatusCode,
  type LLMErrorCode,
  type LLMStatusCode,
} from "@/lib/llm-event-codes";

export const BASE_URL =
  typeof window !== "undefined"
    ? (process.env.NEXT_PUBLIC_API_URL ?? window.location.origin)
    : "http://localhost:8001";

export function getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("jaot_api_key");
}

/**
 * Parse raw SSE text into structured events.
 * SSE format: "event: <type>\ndata: <json>\n\n"
 */
export function parseSSEEvents(text: string): SSEEvent[] {
  const events: SSEEvent[] = [];
  // sse-starlette emits CRLF — normalize before splitting.
  const blocks = text.replace(/\r\n/g, "\n").split("\n\n");

  for (const block of blocks) {
    if (!block.trim()) continue;

    let eventType = "delta";
    let data = "";

    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) {
        eventType = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        data = line.slice(5).trim();
      }
    }

    if (data) {
      events.push({ event: eventType as SSEEvent["event"], data });
    }
  }

  return events;
}

export interface FormulationStreamState {
  /** Accumulated text chunks from delta events */
  chunks: string[];
  /** Raw accumulated text from all delta events */
  rawText: string;
  /** Parsed formulation when received */
  formulation: Formulation | null;
  /** Validation errors when received */
  validationErrors: ValidationError[];
  /** Whether the stream is currently active */
  streaming: boolean;
  /** Stable backend error code (null when no error). Map to i18n via
   *  resolveErrorKey() — never render raw. */
  errorCode: LLMErrorCode | null;
  /** Stable backend status code (null when no active status). Map to i18n
   *  via resolveStatusKey() — never render raw. */
  statusCode: LLMStatusCode | null;
  /** Request id from X-Request-ID middleware, echoed in every status /
   *  error event. Users cite it to support; admin looks it up in logs. */
  requestId: string | null;
  /** Warning message when partial result returned */
  partialWarning: string | null;
  /** Send a message to the conversation */
  sendMessage: (message: string, options?: { useAdvancedModel?: boolean; responseType?: "formulation" | "explanation" }) => Promise<void>;
  /** Abort the current stream */
  stopGenerating: () => void;
}

/**
 * React hook for POST-based SSE streaming using fetch + ReadableStream.
 *
 * Uses POST (not EventSource) because we need to send a request body.
 * Reads the response as a stream and parses SSE events in real-time.
 */
export function useFormulationStream(conversationId: string): FormulationStreamState {
  const [chunks, setChunks] = useState<string[]>([]);
  const [rawText, setRawText] = useState("");
  const [formulation, setFormulation] = useState<Formulation | null>(null);
  const [validationErrors, setValidationErrors] = useState<ValidationError[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [errorCode, setErrorCode] = useState<LLMErrorCode | null>(null);
  const [statusCode, setStatusCode] = useState<LLMStatusCode | null>(null);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [partialWarning, setPartialWarning] = useState<string | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);

  const stopGenerating = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setStreaming(false);
  }, []);

  const sendMessage = useCallback(
    async (message: string, options?: { useAdvancedModel?: boolean; responseType?: "formulation" | "explanation" }) => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }

      setChunks([]);
      setRawText("");
      setFormulation(null);
      setValidationErrors([]);
      setErrorCode(null);
      setStatusCode(null);
      setRequestId(null);
      setPartialWarning(null);
      setStreaming(true);

      const controller = new AbortController();
      abortControllerRef.current = controller;

      try {
        const apiKey = getApiKey();
        const headers: Record<string, string> = {
          "Content-Type": "application/json",
        };
        if (apiKey) {
          headers["Authorization"] = `Bearer ${apiKey}`;
        }

        const response = await fetch(
          `${BASE_URL}/api/v2/llm/conversations/${conversationId}/messages`,
          {
            method: "POST",
            headers,
            body: JSON.stringify({
              message,
              use_advanced_model: options?.useAdvancedModel ?? false,
              ...(options?.responseType && { response_type: options.responseType }),
            }),
            signal: controller.signal,
          }
        );

        if (!response.ok) {
          // Pre-stream failures (402, 429, 5xx) emit no SSE events, so map status → stable code.
          // Other statuses fall back to internal_error; never surface raw response body to avoid
          // leaking upstream detail (Anthropic errors, DB errors, etc.).
          const requestIdHeader = response.headers.get("x-request-id");
          setRequestId(requestIdHeader);
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

        // Capture request id from headers so we can echo it on any error event that omits it.
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
              const events = parseSSEEvents(buffer);
              processEvents(events);
            }
            setStreaming(false);
            break;
          }

          buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

          const lastDoubleNewline = buffer.lastIndexOf("\n\n");
          if (lastDoubleNewline !== -1) {
            const complete = buffer.slice(0, lastDoubleNewline + 2);
            buffer = buffer.slice(lastDoubleNewline + 2);

            const events = parseSSEEvents(complete);
            processEvents(events);
          }
        }
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === "AbortError") {
          return; // user cancelled
        }
        // Network-level failure — surface a stable code so the UI shows the localized
        // generic message instead of the browser's raw err.message.
        setErrorCode("service_unavailable");
        setStreaming(false);
      } finally {
        if (abortControllerRef.current === controller) {
          abortControllerRef.current = null;
        }
      }
    },
    [conversationId]
  );

  function processEvents(events: SSEEvent[]) {
    for (const event of events) {
      switch (event.event) {
        case "delta": {
          try {
            const parsed = JSON.parse(event.data) as { text: string };
            setChunks((prev) => [...prev, parsed.text]);
            setRawText((prev) => prev + parsed.text);
          } catch {
            // fallback: treat data as raw text
            setChunks((prev) => [...prev, event.data]);
            setRawText((prev) => prev + event.data);
          }
          break;
        }
        case "formulation": {
          try {
            const parsed = JSON.parse(event.data) as { formulation: Formulation };
            setFormulation(parsed.formulation);
          } catch { /* invalid JSON */ }
          break;
        }
        case "validation_errors": {
          try {
            const parsed = JSON.parse(event.data) as { errors: ValidationError[] };
            setValidationErrors(parsed.errors);
          } catch { /* invalid JSON */ }
          break;
        }
        case "done": {
          setStreaming(false);
          break;
        }
        case "status": {
          try {
            const parsed = JSON.parse(event.data) as {
              code?: string;
              request_id?: string;
            };
            // Narrow to the typed union: unknown codes are dropped so UI never shows raw
            // identifiers. Equality guards prevent no-op re-renders during streaming.
            if (isLLMStatusCode(parsed.code)) {
              const code = parsed.code;
              setStatusCode((prev) => (prev === code ? prev : code));
            }
            if (parsed.request_id) {
              setRequestId((prev) => prev === parsed.request_id ? prev : parsed.request_id!);
            }
          } catch { /* non-critical: status loss is acceptable */ }
          break;
        }
        case "partial_result": {
          try {
            const parsed = JSON.parse(event.data) as { formulation: Formulation; warning: string };
            setFormulation(parsed.formulation);
            setPartialWarning(parsed.warning);
          } catch { /* ignore */ }
          break;
        }
        case "error": {
          try {
            const parsed = JSON.parse(event.data) as {
              code?: string;
              request_id?: string;
            };
            // Unknown codes fall back to internal_error so we never render upstream detail.
            setErrorCode(
              isLLMErrorCode(parsed.code) ? parsed.code : "internal_error",
            );
            if (parsed.request_id) {
              setRequestId((prev) => prev === parsed.request_id ? prev : parsed.request_id!);
            }
          } catch {
            setErrorCode("internal_error");
          }
          setStreaming(false);
          break;
        }
      }
    }
  }

  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  return {
    chunks,
    rawText,
    formulation,
    validationErrors,
    streaming,
    errorCode,
    statusCode,
    requestId,
    partialWarning,
    sendMessage,
    stopGenerating,
  };
}
