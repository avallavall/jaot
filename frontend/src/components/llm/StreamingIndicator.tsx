"use client";

import { Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTranslations } from "next-intl";
import { resolveStatusKey } from "@/lib/llm-event-codes";

interface StreamingIndicatorProps {
  streaming: boolean;
  onStop: () => void;
  /** Stable backend status code from the SSE stream. The component resolves
   *  it to a localized message via next-intl; unknown codes fall back to
   *  the generic "generating" string. */
  statusCode?: string | null;
}

/**
 * Shows animated dots and a "Stop generating" button during LLM streaming.
 * Renders nothing when not streaming.
 *
 * Status text is resolved from a stable backend code (generating,
 * generating_variables, generating_constraints, assembling) — never from a
 * raw string, so we never leak upstream detail (token counts, retry state)
 * to the chat UI.
 */
export function StreamingIndicator({ streaming, onStop, statusCode }: StreamingIndicatorProps) {
  const t = useTranslations("builder");
  if (!streaming) return null;

  const displayText = t(resolveStatusKey(statusCode));

  return (
    <div className="flex items-center gap-3 px-4 py-2">
      <div className="flex items-center gap-1">
        <span className="h-1.5 w-1.5 rounded-full bg-foreground/40 animate-bounce [animation-delay:0ms]" />
        <span className="h-1.5 w-1.5 rounded-full bg-foreground/40 animate-bounce [animation-delay:150ms]" />
        <span className="h-1.5 w-1.5 rounded-full bg-foreground/40 animate-bounce [animation-delay:300ms]" />
      </div>
      <span className="text-xs text-muted-foreground">{displayText}</span>
      <Button
        variant="outline"
        size="sm"
        onClick={onStop}
        className="ml-auto h-7 gap-1.5 text-xs border-destructive/50 text-destructive hover:bg-destructive/10"
      >
        <Square className="w-3 h-3" />
        {t("llm.streaming.stopGenerating")}
      </Button>
    </div>
  );
}
