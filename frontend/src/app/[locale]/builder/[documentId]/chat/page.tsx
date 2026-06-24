"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { Conversation, ChatMessage as ChatMessageType, Formulation, AttachmentInfo } from "@/lib/llm-types";
import type { OptimizationProblem, PaginatedResponse, SolveResult } from "@/lib/types";
import { SolveResultsDrawer } from "@/components/builder/SolveResultsDrawer";
import { useFormulationStream } from "@/hooks/useSSE";
import { ChatPanel } from "@/components/llm/ChatPanel";
import { FormulationPanel } from "@/components/llm/FormulationPanel";
import { CreditEstimate } from "@/components/llm/CreditEstimate";
import { WorkspaceBreadcrumb } from "@/components/layout/WorkspaceBreadcrumb";
import { Skeleton } from "@/components/ui/skeleton";
import { formulationToCanvas, isParametricFormulation } from "@/lib/builder/formulationToCanvas";
import { FormulationRating } from "@/components/feedback/FormulationRating";
import { useTranslations } from "next-intl";

/** Split-pane: chat (left) + formulation (right). SSE hook is lifted here so both panels share state. */
export default function ChatPage() {
  const t = useTranslations("builder");
  const params = useParams<{ documentId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const documentId = params?.documentId ?? "";
  const solveStatus = searchParams?.get("solveStatus") ?? undefined;

  const [conversationId, setConversationId] = useState<string | null>(null);
  const [initialMessages, setInitialMessages] = useState<ChatMessageType[]>([]);
  const [currentFormulation, setCurrentFormulation] = useState<Formulation | null>(null);
  const [loading, setLoading] = useState(true);
  const [aiMessageCount, setAiMessageCount] = useState(0);
  const [attachment, setAttachment] = useState<AttachmentInfo | null>(null);
  const [uploading, setUploading] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [solving, setSolving] = useState(false);
  const [solveResult, setSolveResult] = useState<SolveResult | null>(null);
  const closeSolveDrawer = useCallback(() => setSolveResult(null), []);
  const hasRenamedRef = useRef(false);

  useEffect(() => {
    if (!documentId) return;

    async function initConversation() {
      try {
        const response = await api.request<PaginatedResponse<Conversation>>(
          "/api/v2/llm/conversations",
          { params: { model_id: documentId } }
        );
        const conversations = response.items;

        if (conversations.length > 0) {
          const conv = conversations[0];
          setConversationId(conv.id);
          setInitialMessages(conv.messages ?? []);
          if (conv.current_formulation) {
            setCurrentFormulation(conv.current_formulation);
          }
        } else {
          const newConv = await api.request<Conversation>(
            "/api/v2/llm/conversations",
            {
              method: "POST",
              body: JSON.stringify({ model_id: documentId }),
            }
          );
          setConversationId(newConv.id);
          setInitialMessages(newConv.messages ?? []);
        }
      } catch {
        toast.error(t("chat.loadFailed"));
      } finally {
        setLoading(false);
      }
    }

    initConversation();
  }, [documentId, t]);

  const stream = useFormulationStream(conversationId ?? "");

  const handleFormulationReady = useCallback((formulation: Formulation) => {
    setCurrentFormulation(formulation);
    setAiMessageCount((c) => c + 1);

    // Best-effort rename to problem_name on the first formulation only.
    if (
      !hasRenamedRef.current &&
      formulation.problem_name &&
      formulation.problem_name !== "not_applicable"
    ) {
      hasRenamedRef.current = true;
      const name = formulation.problem_name
        .replace(/_/g, " ")
        .replace(/\b\w/g, (c) => c.toUpperCase());
      api.updateBuilderDocument(documentId, { name }).catch(() => { /* best-effort */ });
    }
  }, [documentId]);

  const handleOpenInBuilder = useCallback(() => {
    const formulation = stream.formulation ?? currentFormulation;
    if (!formulation) return;

    if (isParametricFormulation(formulation)) {
      toast.error(t("aiAssistant.parametricError"));
      return;
    }

    const result = formulationToCanvas(formulation);

    if ("error" in result) {
      toast.error(result.error);
      return;
    }

    api
      .updateBuilderDocument(documentId, {
        canvas_json: { nodes: result.nodes, edges: result.edges },
      })
      .then(() => {
        router.push(`/builder/${documentId}`);
      })
      .catch((err) => {
        toast.error(t("aiAssistant.canvasSaveFailed", { message: err instanceof Error ? err.message : t("aiAssistant.unknownError") }));
      });
  }, [stream.formulation, currentFormulation, documentId, router, t]);

  const handleExplainFailure = useCallback(
    (status: string) => {
      const message = t("llm.explainPrompt", { status });
      setAiMessageCount((c) => c + 1);
      stream.sendMessage(message, { responseType: "explanation" });
    },
    [stream, t]
  );

  const handleFileSelected = useCallback(async (file: File) => {
    if (!conversationId) return;
    setUploading(true);
    try {
      const result = await api.attachments.upload(conversationId, file);
      if (attachment) {
        toast.success(t("llm.attachment.replace"));
      }
      setAttachment(result);
    } catch (uploadErr) {
      const message = uploadErr instanceof ApiError ? (uploadErr.detail || uploadErr.message) : "Unknown error";
      toast.error(t("llm.attachment.uploadFailed", { error: message }));
    } finally {
      setUploading(false);
    }
  }, [conversationId, attachment, t]);

  const handleRemoveAttachment = useCallback(async () => {
    if (!conversationId || !attachment) return;
    setRemoving(true);
    try {
      await api.attachments.remove(conversationId, attachment.id);
      setAttachment(null);
    } catch {
      toast.error(t("llm.attachment.uploadFailed", { error: "Remove failed" }));
    } finally {
      setRemoving(false);
    }
  }, [conversationId, attachment, t]);

  const handleSolve = useCallback(async () => {
    const formulation = stream.formulation ?? currentFormulation;
    if (!formulation) return;

    // Solver requires flat (non-parametric) variables. Reject early instead of letting
    // the backend return an opaque 422/500 on x_{i,j} / ∑_{i ∈ items} / ∀j patterns.
    if (isParametricFormulation(formulation)) {
      toast.error(t("aiAssistant.parametricError"));
      return;
    }

    setSolving(true);
    try {
      const problem: OptimizationProblem = {
        name: formulation.problem_name || "ai_formulation",
        description: formulation.summary || "",
        variables: formulation.variables.map((v) => ({
          name: v.name,
          type: v.type,
          lower_bound: v.lower_bound,
          upper_bound: v.upper_bound,
        })),
        constraints: formulation.constraints.map((c) => ({
          name: c.name,
          expression: c.expression,
        })),
        objective: {
          sense: formulation.objective.sense,
          expression: formulation.objective.expression,
        },
      };
      const result = await api.solve(problem);
      setSolveResult(result);
    } catch (err) {
      if (err instanceof ApiError && err.status === 402) {
        toast.error(t("aiAssistant.insufficientCredits"));
      } else {
        // Prefer the backend's detail (e.g. "constraint X has unknown variable y") over a generic message.
        const detail = err instanceof ApiError ? (err.detail || err.message) : null;
        const message = detail ?? (err instanceof Error ? err.message : t("aiAssistant.unknownError"));
        toast.error(t("aiAssistant.solveFailed", { message }));
      }
    } finally {
      setSolving(false);
    }
  }, [stream.formulation, currentFormulation, t]);

  if (loading) {
    return (
      <div className="flex flex-col h-screen">
        <div className="px-4 pt-2">
          <WorkspaceBreadcrumb
            section={t("chat.breadcrumbSection")}
            sectionHref="/builder"
            itemName={t("chat.breadcrumbItem")}
          />
        </div>
        <div className="flex-1 flex items-center justify-center">
          <div className="space-y-3 w-64">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-1/2" />
          </div>
        </div>
      </div>
    );
  }

  if (!conversationId) {
    return (
      <div className="flex flex-col h-screen">
        <div className="px-4 pt-2">
          <WorkspaceBreadcrumb
            section={t("chat.breadcrumbSection")}
            sectionHref="/builder"
            itemName={t("chat.breadcrumbItem")}
          />
        </div>
        <div className="flex-1 flex items-center justify-center">
          <p className="text-muted-foreground">
            {t("chat.conversationFailed")}
          </p>
        </div>
      </div>
    );
  }

  const displayFormulation = stream.formulation ?? currentFormulation;
  const displayIsParametric = displayFormulation
    ? isParametricFormulation(displayFormulation)
    : false;

  return (
    <div className="flex flex-col h-screen">
      <div className="px-4 pt-2 pb-1 border-b border-border flex-shrink-0">
        <WorkspaceBreadcrumb
          section={t("chat.breadcrumbSection")}
          sectionHref="/builder"
          itemName={t("chat.breadcrumbItem")}
        />
        <h1 className="text-lg font-semibold mt-1 mb-1">{t("chat.title")}</h1>
      </div>

      <div className="flex flex-1 overflow-hidden flex-col md:flex-row">
        <div className="md:w-[45%] w-full h-1/2 md:h-full border-b md:border-b-0 md:border-r border-border flex flex-col">
          <ChatPanel
            initialMessages={initialMessages}
            stream={stream}
            onFormulationReady={handleFormulationReady}
            onExplainFailure={handleExplainFailure}
            solveStatus={solveStatus}
            attachment={attachment}
            uploading={uploading}
            onFileSelected={handleFileSelected}
            onRemoveAttachment={handleRemoveAttachment}
            removing={removing}
          />
        </div>

        <div className="md:w-[55%] w-full h-1/2 md:h-full overflow-y-auto p-4">
          {displayFormulation ? (
            <div className="space-y-4">
              <FormulationPanel
                formulation={displayFormulation}
                validationErrors={stream.validationErrors}
                streaming={stream.streaming}
                rawText={stream.rawText}
                onOpenInBuilder={handleOpenInBuilder}
                onSolve={handleSolve}
                solving={solving}
                parametric={displayIsParametric}
              />
              {!stream.streaming && displayFormulation && (
                <CreditEstimate
                  formulation={displayFormulation}
                  aiMessagesCount={aiMessageCount}
                  documentTokens={attachment?.estimated_tokens}
                />
              )}
              {!stream.streaming && displayFormulation && conversationId && (
                <FormulationRating
                  conversationId={conversationId}
                  formulation={displayFormulation}
                />
              )}
            </div>
          ) : stream.streaming ? (
            <FormulationPanel
              formulation={null}
              validationErrors={[]}
              streaming={true}
              rawText={stream.rawText}
            />
          ) : (
            <div className="flex items-center justify-center h-full text-muted-foreground">
              <div className="text-center space-y-2">
                <p className="text-sm">
                  {t("chat.formulation")}
                </p>
                <p className="text-xs">
                  {t("chat.formulationHint")}
                </p>
              </div>
            </div>
          )}
        </div>
      </div>

      <SolveResultsDrawer
        result={solveResult}
        isOpen={solveResult !== null}
        onClose={closeSolveDrawer}
      />
    </div>
  );
}
