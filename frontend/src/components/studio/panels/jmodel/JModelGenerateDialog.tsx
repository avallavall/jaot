"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { jmodelErrorText } from "@/lib/jmodel-error";
import { toast } from "sonner";
import { FileText, ImageIcon, Loader2, Sparkles, X } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { AdvancedModelToggle } from "@/components/llm/AdvancedModelToggle";
import { useAdvancedModel } from "@/hooks/useAdvancedModel";
import { api, ApiError } from "@/lib/api";
import type { DslGenerateAttachment } from "@/lib/types";

const ACCEPT = "image/png,image/jpeg,image/gif,image/webp,application/pdf";
const ALLOWED_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
  "application/pdf",
]);
const MAX_ATTACHMENTS = 4;
const MAX_FILE_BYTES = 5 * 1024 * 1024; // 5 MB (well under Claude's per-file limit)

interface PendingAttachment extends DslGenerateAttachment {
  name: string;
  isPdf: boolean;
}

/** Read a File into raw base64 (no `data:` URL prefix — the API wants the bytes only). */
function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string; // "data:<mime>;base64,XXXX"
      const comma = result.indexOf(",");
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.onerror = () => reject(reader.error ?? new Error("read failed"));
    reader.readAsDataURL(file);
  });
}

interface JModelGenerateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The existing editor source, passed so the model can refine rather than start fresh. */
  currentSource: string;
  /** Called with the generated JModel source; the panel loads it like a normal edit. */
  onGenerated: (source: string) => void;
}

/**
 * B3 — "Generate with AI" for the JModel lens. Collects a plain-language description
 * and/or screenshots/PDFs of a formulation, sends them to `POST /dsl/generate` (Claude
 * reads attachments with native vision), and hands the returned source back to the
 * editor. The backend runs a compile→retry loop, so a returned source is proven to
 * compile; a rare non-compiling best-effort draft is still loaded (the editor re-flags
 * its error), never silently dropped.
 */
export function JModelGenerateDialog({
  open,
  onOpenChange,
  currentSource,
  onGenerated,
}: JModelGenerateDialogProps) {
  const t = useTranslations("studio");
  const tError = useTranslations("errors.codes");
  const [description, setDescription] = useState("");
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [advanced, setAdvanced] = useAdvancedModel();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const reset = () => {
    setDescription("");
    setAttachments([]);
    setError(null);
    setGenerating(false);
  };

  const handleOpenChange = (next: boolean) => {
    // Don't let a backdrop click abandon an in-flight (billable) generation.
    if (generating && !next) return;
    if (!next) reset();
    onOpenChange(next);
  };

  const handlePickFiles = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = ""; // allow re-picking the same file
    setError(null);

    // Track the count locally: `attachments` is a stale closure inside this async
    // loop, so picking 6 files at once would silently drop the extras (the setter
    // caps) without ever surfacing the "too many" message.
    let count = attachments.length;
    for (const file of files) {
      if (count >= MAX_ATTACHMENTS) {
        setError(t("jmodelGenerateTooMany", { max: MAX_ATTACHMENTS }));
        break;
      }
      if (!ALLOWED_TYPES.has(file.type)) {
        setError(t("jmodelGenerateBadType", { name: file.name }));
        continue;
      }
      if (file.size > MAX_FILE_BYTES) {
        setError(
          t("jmodelGenerateTooLarge", {
            name: file.name,
            mb: Math.round(MAX_FILE_BYTES / (1024 * 1024)),
          }),
        );
        continue;
      }
      try {
        const data = await fileToBase64(file);
        count += 1;
        setAttachments((prev) =>
          prev.length >= MAX_ATTACHMENTS
            ? prev
            : [
                ...prev,
                {
                  media_type: file.type,
                  data,
                  name: file.name,
                  isPdf: file.type === "application/pdf",
                },
              ],
        );
      } catch {
        setError(t("jmodelGenerateBadType", { name: file.name }));
      }
    }
  };

  const removeAttachment = (index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  };

  const canSubmit =
    !generating && (description.trim().length > 0 || attachments.length > 0);

  const handleGenerate = async () => {
    if (!canSubmit) return;
    setGenerating(true);
    setError(null);
    try {
      const res = await api.generateDsl({
        description: description.trim(),
        attachments: attachments.map(({ media_type, data }) => ({
          media_type,
          data,
        })),
        currentSource: currentSource.trim() ? currentSource : null,
        useAdvancedModel: advanced,
      });
      if (!res.source) {
        setError(
          t("jmodelGenerateFailed", { message: jmodelErrorText(res.error, tError) }),
        );
        return;
      }
      onGenerated(res.source);
      if (res.ok) {
        toast.success(t("jmodelGenerateApplied"));
      } else {
        // A best-effort draft that did not compile — loaded anyway; the editor
        // highlights the error so the user can finish it.
        toast.warning(t("jmodelGenerateNotCompiled"));
      }
      reset();
      onOpenChange(false);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "";
      setError(t("jmodelGenerateFailed", { message }));
    } finally {
      setGenerating(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className="sm:max-w-xl"
        data-testid="studio-jmodel-generate-dialog"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            {t("jmodelGenerateTitle")}
          </DialogTitle>
          <DialogDescription>{t("jmodelGenerateDesc")}</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <textarea
            data-testid="studio-jmodel-generate-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={generating}
            rows={5}
            placeholder={t("jmodelGeneratePlaceholder")}
            aria-label={t("jmodelGenerateTitle")}
            className="w-full resize-none rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring disabled:opacity-60"
          />

          {attachments.length > 0 && (
            <ul
              className="flex flex-col gap-1.5"
              data-testid="studio-jmodel-generate-attachments"
            >
              {attachments.map((att, idx) => (
                <li
                  key={`${att.name}-${idx}`}
                  data-testid="studio-jmodel-generate-attachment"
                  className="flex items-center gap-2 rounded-md border bg-muted/30 px-2 py-1 text-xs"
                >
                  {att.isPdf ? (
                    <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  ) : (
                    <ImageIcon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  )}
                  <span className="min-w-0 flex-1 truncate">{att.name}</span>
                  {!generating && (
                    <button
                      type="button"
                      onClick={() => removeAttachment(idx)}
                      title={t("jmodelGenerateRemove")}
                      className="shrink-0 rounded-full p-0.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}

          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-testid="studio-jmodel-generate-attach"
              disabled={generating || attachments.length >= MAX_ATTACHMENTS}
              onClick={() => fileInputRef.current?.click()}
              className="h-7 gap-1.5 text-xs"
            >
              <ImageIcon className="h-3.5 w-3.5" />
              {t("jmodelGenerateAttach")}
            </Button>
            <span className="text-xs text-muted-foreground">
              {t("jmodelGenerateAttachHint", { max: MAX_ATTACHMENTS })}
            </span>
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPT}
              multiple
              onChange={handlePickFiles}
              className="hidden"
              disabled={generating}
            />
          </div>

          {error && (
            <p
              data-testid="studio-jmodel-generate-error"
              className="text-xs text-destructive"
            >
              {error}
            </p>
          )}

          {generating && (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {t("jmodelGenerateRunning")}
            </p>
          )}
        </div>

        <DialogFooter className="sm:justify-between">
          {/* The advanced model costs more per call, so it is an explicit opt-in here too —
              this dialog is an LLM surface like the chats and the explainers. */}
          <AdvancedModelToggle
            checked={advanced}
            onChange={setAdvanced}
            disabled={generating}
          />
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              disabled={generating}
              onClick={() => handleOpenChange(false)}
            >
              {t("jmodelGenerateCancel")}
            </Button>
            <Button
              type="button"
              data-testid="studio-jmodel-generate-submit"
              disabled={!canSubmit}
              onClick={handleGenerate}
              className="gap-1.5"
            >
              {generating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}
              {t("jmodelGenerateSubmit")}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
