"use client";

import { cn } from "@/lib/utils";
import type { ChatMessage as ChatMessageType } from "@/lib/llm-types";
import { useTranslations } from "next-intl";

interface ChatMessageProps {
  message: ChatMessageType;
  isLatest: boolean;
}

function formatTime(dateStr: string): string {
  try {
    const date = new Date(dateStr);
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

/**
 * Individual chat message bubble.
 * User messages are right-aligned with primary background.
 * Assistant messages are left-aligned with muted background.
 */
export function ChatMessage({ message, isLatest }: ChatMessageProps) {
  const t = useTranslations("builder");
  const isUser = message.role === "user";
  const isSystem = message.role === "system";

  // Check if assistant message references validation errors
  const validationMatch = message.content.match(/(\d+)\s*(issue|error|problem)/i);
  const hasValidationContext =
    !isUser && message.formulation_json !== null && validationMatch;

  return (
    <div
      className={cn(
        "flex w-full",
        isUser ? "justify-end" : "justify-start",
        isLatest && "animate-in fade-in slide-in-from-bottom-2 duration-300"
      )}
    >
      <div
        className={cn(
          "max-w-[80%] rounded-lg px-4 py-2.5",
          isUser
            ? "bg-primary text-primary-foreground"
            : isSystem
              ? "bg-yellow-50 dark:bg-yellow-900/20 text-foreground border border-yellow-200 dark:border-yellow-800"
              : "bg-muted text-foreground"
        )}
      >
        <p className="text-sm whitespace-pre-wrap">{message.content}</p>

        {hasValidationContext && (
          <p className="text-xs mt-2 opacity-80 border-t border-current/10 pt-1.5">
            {t("llm.chat.validationContext", { count: parseInt(validationMatch[1]), type: validationMatch[2] })}
          </p>
        )}

        <p
          className={cn(
            "text-[0.625rem] mt-1",
            isUser ? "text-primary-foreground/60" : "text-muted-foreground"
          )}
        >
          {formatTime(message.created_at)}
        </p>
      </div>
    </div>
  );
}
