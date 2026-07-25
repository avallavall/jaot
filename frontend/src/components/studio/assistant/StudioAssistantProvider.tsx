"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { useAdvancedModel } from "@/hooks/useAdvancedModel";
import { useStore } from "zustand";
import { api, ApiError } from "@/lib/api";
import type {
  AttachmentInfo,
  ChatMessage as ChatMessageType,
  Conversation,
  Formulation,
} from "@/lib/llm-types";
import type { PaginatedResponse } from "@/lib/types";
import { useFormulationStream, type FormulationStreamState } from "@/hooks/useSSE";
import { resolveErrorKey } from "@/lib/llm-event-codes";
import { formulationToProblem } from "@/lib/builder/formulationToProblem";
import { humanizeProblemName, isRealFormulation } from "./formulation-adopt";
import type { ModelProjectStore } from "../store/createModelProjectStore";

/**
 * The studio AI Assistant session — lifted to the workspace provider so it OUTLIVES
 * the Build "Assistant" sub-lens AND the top-level Build/Analyze/Solve tab. The SSE
 * generation, the conversation, and the message list all live here, not inside the
 * unmounting `AssistantLens`. This is the AI-chat analogue of the durable solve
 * session (`useSolveSession`): switching tabs mid-generation no longer aborts the
 * stream or loses the work, and a formulation that finishes while you're on another
 * tab still lands in the canonical model.
 *
 * The conversation is bootstrapped LAZILY (`ensureBootstrapped`, called by the lens
 * on first open) so opening a project you never chat in costs nothing. The provider
 * renders `{children}` (a stable element) so its per-delta re-renders never reach the
 * workspace tree — only `useStudioAssistant()` consumers (the lens) re-render.
 */
export interface StudioAssistantSession {
  /** Whether a conversation is ready (bootstrap completed). */
  ready: boolean;
  /** Bootstrap (find-or-create) is in flight. */
  loading: boolean;
  /** The displayed conversation: persisted history + this session's turns. */
  messages: ChatMessageType[];
  /** The lifted SSE stream — shared with the chat panel for live status. */
  stream: FormulationStreamState;
  /** Send a user message (appends it + starts the stream). No-op while streaming. */
  send: (text: string) => void;
  attachment: AttachmentInfo | null;
  uploading: boolean;
  removing: boolean;
  onFileSelected: (file: File) => void;
  onRemoveAttachment: () => void;
  /** Idempotently create-or-load the project's conversation. */
  ensureBootstrapped: () => void;
}

const StudioAssistantContext = createContext<StudioAssistantSession | null>(null);

/** Read the studio assistant session. Throws if used outside its provider. */
export function useStudioAssistant(): StudioAssistantSession {
  const ctx = useContext(StudioAssistantContext);
  if (!ctx) {
    throw new Error("useStudioAssistant must be used within a StudioAssistantProvider");
  }
  return ctx;
}

interface StudioAssistantProviderProps {
  store: ModelProjectStore;
  children: React.ReactNode;
}

export function StudioAssistantProvider({ store, children }: StudioAssistantProviderProps) {
  const tStudio = useTranslations("studio");
  const tChat = useTranslations("builder");
  const modelId = useStore(store, (s) => s.modelId);

  const [conversationId, setConversationId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // Read from the shared store the toggle writes to, so a flip in the chat panel
  // applies to the very next message this provider sends.
  const [advancedModel] = useAdvancedModel();
  const [messages, setMessages] = useState<ChatMessageType[]>([]);
  const [attachment, setAttachment] = useState<AttachmentInfo | null>(null);
  const [uploading, setUploading] = useState(false);
  const [removing, setRemoving] = useState(false);

  // Guards so the bootstrap runs once and each stream result is consumed once.
  const bootstrapStartedRef = useRef(false);
  const lastFormulationRef = useRef<Formulation | null>(null);
  const lastErrorRef = useRef<string | null>(null);
  const hasRenamedRef = useRef(false);

  const stream = useFormulationStream(conversationId ?? "");

  const ensureBootstrapped = useCallback(() => {
    if (bootstrapStartedRef.current) return;
    if (!modelId || modelId === "new") return;
    bootstrapStartedRef.current = true;
    setLoading(true);
    (async () => {
      try {
        // Reuse this project's conversation if one exists, else create one scoped to it.
        const resp = await api.request<PaginatedResponse<Conversation>>(
          "/api/v2/llm/conversations",
          { params: { model_project_id: modelId } }
        );
        if (resp.items.length > 0) {
          setConversationId(resp.items[0].id);
          setMessages(resp.items[0].messages ?? []);
        } else {
          const conv = await api.request<Conversation>("/api/v2/llm/conversations", {
            method: "POST",
            body: JSON.stringify({ model_project_id: modelId }),
          });
          setConversationId(conv.id);
          setMessages(conv.messages ?? []);
        }
      } catch {
        bootstrapStartedRef.current = false; // allow a retry on next open
        toast.error(tStudio("assistantLoadFailed"));
      } finally {
        setLoading(false);
      }
    })();
  }, [modelId, tStudio]);

  const send = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || !conversationId) return;
      if (stream.streaming) {
        toast.info(tChat("llm.chat.waitForGeneration"));
        return;
      }
      setMessages((prev) => [
        ...prev,
        {
          id: `usr_${Date.now()}`,
          role: "user",
          content: trimmed,
          formulation_json: null,
          created_at: new Date().toISOString(),
        },
      ]);
      void stream.sendMessage(trimmed, { useAdvancedModel: advancedModel });
    },
    [conversationId, stream, tChat, advancedModel]
  );

  // A completed formulation: append the assistant turn AND fold it into the canonical
  // model. Done here (provider level) — not in the lens — so it still applies if the
  // generation finishes while the user is on the canvas/editor or another tab.
  useEffect(() => {
    const f = stream.formulation;
    if (!f || f === lastFormulationRef.current) return;
    lastFormulationRef.current = f;

    setMessages((prev) => [
      ...prev,
      {
        id: `msg_${Date.now()}`,
        role: "assistant",
        content: f.summary || tChat("llm.chat.generatedFormulation"),
        formulation_json: f,
        created_at: new Date().toISOString(),
      },
    ]);

    // A refusal / variable-less answer must never overwrite the model with nothing.
    if (!isRealFormulation(f)) return;
    store.getState().setProblem(formulationToProblem(f), { source: "formulation" });

    // Adopt the AI's problem name on the first real formulation (best-effort rename).
    if (!hasRenamedRef.current && f.problem_name) {
      hasRenamedRef.current = true;
      const name = humanizeProblemName(f.problem_name);
      store.getState().setName(name);
      api.updateProject(modelId, { name }).catch(() => {
        /* best-effort rename */
      });
    }
  }, [stream.formulation, store, modelId, tChat]);

  // A stream error surfaces as an assistant message (localized from a stable code —
  // never a raw upstream string). The request id is appended so users can cite it.
  useEffect(() => {
    const code = stream.errorCode;
    if (!code || code === lastErrorRef.current) return;
    lastErrorRef.current = code;
    const localizedError = tChat(resolveErrorKey(code));
    setMessages((prev) => [
      ...prev,
      {
        id: `err_${Date.now()}`,
        role: "assistant",
        content: stream.requestId
          ? tChat("llm.chat.errorWithRequestId", {
              error: localizedError,
              requestId: stream.requestId,
            })
          : tChat("llm.chat.errorPrefix", { error: localizedError }),
        formulation_json: null,
        created_at: new Date().toISOString(),
      },
    ]);
    // requestId read as a snapshot; adding it as a dep would re-fire and duplicate.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream.errorCode, tChat]);

  const onFileSelected = useCallback(
    async (file: File) => {
      if (!conversationId) return;
      setUploading(true);
      try {
        const result = await api.attachments.upload(conversationId, file);
        if (attachment) toast.success(tStudio("assistantAttachmentReplaced"));
        setAttachment(result);
      } catch (err) {
        const message =
          err instanceof ApiError ? err.detail || err.message : tStudio("assistantAttachmentFailed");
        toast.error(message);
      } finally {
        setUploading(false);
      }
    },
    [conversationId, attachment, tStudio]
  );

  const onRemoveAttachment = useCallback(async () => {
    if (!conversationId || !attachment) return;
    setRemoving(true);
    try {
      await api.attachments.remove(conversationId, attachment.id);
      setAttachment(null);
    } catch {
      toast.error(tStudio("assistantAttachmentFailed"));
    } finally {
      setRemoving(false);
    }
  }, [conversationId, attachment, tStudio]);

  const value: StudioAssistantSession = {
    ready: conversationId !== null,
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
  };

  return (
    <StudioAssistantContext.Provider value={value}>{children}</StudioAssistantContext.Provider>
  );
}
