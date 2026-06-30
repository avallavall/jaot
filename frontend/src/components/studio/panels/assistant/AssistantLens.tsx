"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { api, ApiError } from "@/lib/api";
import type {
  AttachmentInfo,
  ChatMessage as ChatMessageType,
  Conversation,
  Formulation,
} from "@/lib/llm-types";
import type { PaginatedResponse } from "@/lib/types";
import { useFormulationStream } from "@/hooks/useSSE";
import { ChatPanel } from "@/components/llm/ChatPanel";
import { Skeleton } from "@/components/ui/skeleton";
import { formulationToProblem } from "@/lib/builder/formulationToProblem";
import {
  useModelProjectStore,
  useModelProjectStoreApi,
} from "../../store/useModelProjectStore";

/**
 * The Build "Assistant" sub-lens: the natural-language model builder, embedded in
 * the studio and scoped to the live `ModelProject`. The conversation is seeded with
 * the project's current model (P4b.1 backend), so the first message refines what's
 * already there. Each produced formulation flows into the canonical store via
 * `setProblem({source:"formulation"})` — reflected on the canvas/editor/Analyze and
 * autosaved — so the AI builds AND edits the same model the other lenses show. The
 * studio itself is the model view, so this lens is chat-only (no FormulationPanel).
 */
export function AssistantLens() {
  const t = useTranslations("studio");
  const modelId = useModelProjectStore((s) => s.modelId);
  const storeApi = useModelProjectStoreApi();

  const [conversationId, setConversationId] = useState<string | null>(null);
  const [initialMessages, setInitialMessages] = useState<ChatMessageType[]>([]);
  const [loading, setLoading] = useState(true);
  const [attachment, setAttachment] = useState<AttachmentInfo | null>(null);
  const [uploading, setUploading] = useState(false);
  const [removing, setRemoving] = useState(false);
  const hasRenamedRef = useRef(false);

  useEffect(() => {
    if (!modelId || modelId === "new") {
      setLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        // Reuse this project's conversation if one exists, else create one scoped to it.
        const resp = await api.request<PaginatedResponse<Conversation>>(
          "/api/v2/llm/conversations",
          { params: { model_project_id: modelId } }
        );
        if (cancelled) return;
        if (resp.items.length > 0) {
          setConversationId(resp.items[0].id);
          setInitialMessages(resp.items[0].messages ?? []);
        } else {
          const conv = await api.request<Conversation>("/api/v2/llm/conversations", {
            method: "POST",
            body: JSON.stringify({ model_project_id: modelId }),
          });
          if (cancelled) return;
          setConversationId(conv.id);
          setInitialMessages(conv.messages ?? []);
        }
      } catch {
        if (!cancelled) toast.error(t("assistantLoadFailed"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [modelId, t]);

  const stream = useFormulationStream(conversationId ?? "");

  const handleFormulationReady = useCallback(
    (formulation: Formulation) => {
      // A refusal / empty result must never overwrite the model with nothing.
      if (formulation.problem_name === "not_applicable" || !formulation.variables?.length) {
        return;
      }
      storeApi.getState().setProblem(formulationToProblem(formulation), { source: "formulation" });

      // Adopt the AI's problem name on the first real formulation (project untitled-only).
      if (!hasRenamedRef.current && formulation.problem_name) {
        hasRenamedRef.current = true;
        const name = formulation.problem_name
          .replace(/_/g, " ")
          .replace(/\b\w/g, (c) => c.toUpperCase());
        storeApi.getState().setName(name);
        api.updateProject(modelId, { name }).catch(() => {
          /* best-effort rename */
        });
      }
    },
    [storeApi, modelId]
  );

  const handleFileSelected = useCallback(
    async (file: File) => {
      if (!conversationId) return;
      setUploading(true);
      try {
        const result = await api.attachments.upload(conversationId, file);
        if (attachment) toast.success(t("assistantAttachmentReplaced"));
        setAttachment(result);
      } catch (err) {
        const message =
          err instanceof ApiError ? err.detail || err.message : t("assistantAttachmentFailed");
        toast.error(message);
      } finally {
        setUploading(false);
      }
    },
    [conversationId, attachment, t]
  );

  const handleRemoveAttachment = useCallback(async () => {
    if (!conversationId || !attachment) return;
    setRemoving(true);
    try {
      await api.attachments.remove(conversationId, attachment.id);
      setAttachment(null);
    } catch {
      toast.error(t("assistantAttachmentFailed"));
    } finally {
      setRemoving(false);
    }
  }, [conversationId, attachment, t]);

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

  if (!conversationId) {
    return (
      <div className="flex-1 flex items-center justify-center p-6 text-center text-sm text-muted-foreground">
        {t("assistantUnavailable")}
      </div>
    );
  }

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <ChatPanel
        initialMessages={initialMessages}
        stream={stream}
        onFormulationReady={handleFormulationReady}
        attachment={attachment}
        uploading={uploading}
        onFileSelected={handleFileSelected}
        onRemoveAttachment={handleRemoveAttachment}
        removing={removing}
      />
    </div>
  );
}
