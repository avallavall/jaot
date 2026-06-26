"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Send, HelpCircle, AlertTriangle, Paperclip, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { ChatMessage as ChatMessageType, Formulation, AttachmentInfo } from "@/lib/llm-types";
import type { FormulationStreamState } from "@/hooks/useSSE";
import { resolveErrorKey } from "@/lib/llm-event-codes";
import { ByokHint } from "@/components/llm/ByokHint";
import { ChatMessage } from "./ChatMessage";
import { ExamplePrompts } from "./ExamplePrompts";
import { FileAttachmentChip } from "./FileAttachmentChip";
import { StreamingIndicator } from "./StreamingIndicator";
import { useTranslations } from "next-intl";

interface ChatPanelProps {
  initialMessages: ChatMessageType[];
  stream: FormulationStreamState;
  onFormulationReady: (formulation: Formulation) => void;
  onExplainFailure?: (status: string) => void;
  /** Shows "Explain with AI" button when infeasible/unbounded. */
  solveStatus?: string;
  attachment?: AttachmentInfo | null;
  uploading?: boolean;
  onFileSelected?: (file: File) => void;
  onRemoveAttachment?: () => void;
  removing?: boolean;
}

export function ChatPanel({ initialMessages, stream, onFormulationReady, onExplainFailure, solveStatus, attachment, uploading, onFileSelected, onRemoveAttachment, removing }: ChatPanelProps) {
  const t = useTranslations("builder");
  const [messages, setMessages] = useState<ChatMessageType[]>(initialMessages);
  const [inputText, setInputText] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const dragCounter = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const prevFormulationRef = useRef<Formulation | null>(null);

  const handleFileSelected = useCallback(
    (file: File) => {
      const ALLOWED_EXTENSIONS = [".pdf", ".csv", ".txt"];
      const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB
      if (file.size > MAX_FILE_SIZE) {
        toast.error(t("llm.attachment.fileTooLarge"));
        return;
      }
      const ext = file.name.substring(file.name.lastIndexOf(".")).toLowerCase();
      if (!ALLOWED_EXTENSIONS.includes(ext)) {
        toast.error(t("llm.attachment.unsupportedType"));
        return;
      }
      onFileSelected?.(file);
    },
    [onFileSelected, t]
  );

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current += 1;
    setIsDragging(true);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current -= 1;
    if (dragCounter.current === 0) {
      setIsDragging(false);
    }
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragCounter.current = 0;
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) {
        handleFileSelected(file);
      }
    },
    [handleFileSelected]
  );

  useEffect(() => {
    setMessages(initialMessages);
  }, [initialMessages]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, stream.streaming]);

  useEffect(() => {
    if (stream.formulation && stream.formulation !== prevFormulationRef.current) {
      prevFormulationRef.current = stream.formulation;

      // A refusal ("not_applicable") or variable-less formulation must NOT replace
      // the user's current model — that would wipe their work. Still surface the
      // assistant's text answer below so questions/diagnoses are visible.
      const isRealModel =
        stream.formulation.problem_name !== "not_applicable" &&
        (stream.formulation.variables?.length ?? 0) > 0;
      if (isRealModel) {
        onFormulationReady(stream.formulation);
      }

      const assistantMsg: ChatMessageType = {
        id: `msg_${Date.now()}`,
        role: "assistant",
        content: stream.formulation.summary || t("llm.chat.generatedFormulation"),
        formulation_json: stream.formulation,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    }
  }, [stream.formulation, onFormulationReady, t]);

  // Stream errors surface as assistant messages. Text comes from a stable backend code via
  // next-intl — never from a raw string — so we cannot leak upstream detail. The request_id is
  // appended so users can cite it to support.
  useEffect(() => {
    if (stream.errorCode) {
      const localizedError = t(resolveErrorKey(stream.errorCode));
      const errorMsg: ChatMessageType = {
        id: `err_${Date.now()}`,
        role: "assistant",
        content: stream.requestId
          ? t("llm.chat.errorWithRequestId", {
              error: localizedError,
              requestId: stream.requestId,
            })
          : t("llm.chat.errorPrefix", { error: localizedError }),
        formulation_json: null,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    }
  // requestId read as a snapshot inside the effect; adding it as a dep would re-fire and duplicate.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream.errorCode, t]);

  const handleSend = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;

      if (stream.streaming) {
        toast.info(t("llm.chat.waitForGeneration"));
        return;
      }

      const userMsg: ChatMessageType = {
        id: `usr_${Date.now()}`,
        role: "user",
        content: trimmed,
        formulation_json: null,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setInputText("");

      await stream.sendMessage(trimmed);
    },
    [stream, t]
  );

  const handleExampleSelect = useCallback(
    (prompt: string) => {
      handleSend(prompt);
    },
    [handleSend]
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend(inputText);
    }
  };

  const isEmpty = messages.length === 0;

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {isEmpty ? (
          <div className="space-y-4">
            <ExamplePrompts onSelect={handleExampleSelect} />
            <ByokHint />
          </div>
        ) : (
          <>
            {messages.map((msg, idx) => (
              <ChatMessage
                key={msg.id}
                message={msg}
                isLatest={idx === messages.length - 1}
              />
            ))}
            <StreamingIndicator
              streaming={stream.streaming}
              onStop={stream.stopGenerating}
              statusCode={stream.statusCode}
            />
            {stream.partialWarning && !stream.streaming && (
              <Alert className="mx-4 my-2 border-amber-500 bg-amber-50 dark:bg-amber-950/30">
                <AlertTriangle className="h-4 w-4 text-amber-600" />
                <AlertTitle className="text-amber-800 dark:text-amber-400">{t("llm.chat.partialResult")}</AlertTitle>
                <AlertDescription className="text-amber-700 dark:text-amber-300 text-sm">
                  {stream.partialWarning}
                </AlertDescription>
              </Alert>
            )}
            {solveStatus &&
              (solveStatus === "infeasible" || solveStatus === "unbounded") &&
              !stream.streaming &&
              onExplainFailure && (
                <div className="flex justify-center py-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-2"
                    onClick={() => onExplainFailure(solveStatus)}
                  >
                    <HelpCircle className="h-4 w-4" />
                    {t("llm.chat.explainWithAi")}
                  </Button>
                </div>
              )}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      <div
        className={`border-t border-border p-3 relative ${isDragging ? "border-2 border-dashed border-primary/50 bg-primary/5" : ""}`}
        onDragEnter={handleDragEnter}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {isDragging && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-primary/5 rounded">
            <span className="text-sm font-medium text-primary">{t("llm.attachment.dropHere")}</span>
          </div>
        )}

        {uploading && (
          <div className="flex items-center gap-2 mb-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t("llm.attachment.uploading")}
          </div>
        )}
        {!uploading && attachment && onRemoveAttachment && (
          <div className="mb-2">
            <FileAttachmentChip attachment={attachment} onRemove={onRemoveAttachment} removing={removing} />
          </div>
        )}

        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.csv,.txt"
          className="hidden"
          onChange={(e) => {
            if (e.target.files?.[0]) handleFileSelected(e.target.files[0]);
            e.target.value = "";
          }}
        />

        <div className="flex items-end gap-2">
          <Textarea
            ref={textareaRef}
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t("llm.chat.placeholder")}
            className="min-h-[44px] max-h-[120px] resize-none"
            rows={1}
          />
          <Button
            variant="ghost"
            size="icon"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading || stream.streaming}
            aria-label={t("llm.attachment.attachFile")}
            className="flex-shrink-0 h-[44px] w-[44px]"
          >
            <Paperclip className="w-4 h-4" />
          </Button>
          <Button
            size="icon"
            onClick={() => handleSend(inputText)}
            disabled={stream.streaming || !inputText.trim()}
            className="flex-shrink-0 h-[44px] w-[44px]"
          >
            <Send className="w-4 h-4" />
          </Button>
        </div>
        <p className="text-[0.625rem] text-muted-foreground mt-1.5">
          {t("llm.chat.enterToSend")}
        </p>
      </div>
    </div>
  );
}
