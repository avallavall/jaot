"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { ChatPanel } from "@/components/llm/ChatPanel";
import { Skeleton } from "@/components/ui/skeleton";
import { useStudioAssistant } from "../../assistant/StudioAssistantProvider";

/**
 * The Build "Assistant" sub-lens: a thin view over the studio AI session, which is
 * lifted to the workspace provider (`StudioAssistantProvider`). Because the session —
 * the conversation, the SSE stream, and the message list — lives ABOVE this lens, it
 * survives switching sub-lens or tab mid-generation: the stream keeps running and the
 * produced formulation still lands in the canonical model. Here we only ensure the
 * conversation is bootstrapped on first open and render the controlled `ChatPanel`.
 */
export function AssistantLens() {
  const t = useTranslations("studio");
  const {
    ready,
    loading,
    messages,
    stream,
    send,
    attachment,
    uploading,
    removing,
    onFileSelected,
    onRemoveAttachment,
    ensureBootstrapped,
  } = useStudioAssistant();

  useEffect(() => {
    ensureBootstrapped();
  }, [ensureBootstrapped]);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="w-64 space-y-3">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      </div>
    );
  }

  if (!ready) {
    return (
      <div className="flex-1 flex items-center justify-center p-6 text-center text-sm text-muted-foreground">
        {t("assistantUnavailable")}
      </div>
    );
  }

  return (
    <div className="flex flex-col flex-1 min-h-0" data-testid="studio-assistant">
      <ChatPanel
        initialMessages={messages}
        messages={messages}
        onSend={send}
        stream={stream}
        attachment={attachment}
        uploading={uploading}
        onFileSelected={onFileSelected}
        onRemoveAttachment={onRemoveAttachment}
        removing={removing}
      />
    </div>
  );
}
