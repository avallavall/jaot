"use client";

import { FileText, X, Loader2 } from "lucide-react";
import type { AttachmentInfo } from "@/lib/llm-types";
import { useTranslations } from "next-intl";

interface FileAttachmentChipProps {
  attachment: AttachmentInfo;
  onRemove: () => void;
  removing?: boolean;
}

/**
 * Compact chip displaying an attached file's metadata:
 * filename, character count, estimated tokens, preview text, and remove button.
 */
export function FileAttachmentChip({ attachment, onRemove, removing }: FileAttachmentChipProps) {
  const t = useTranslations("builder");

  return (
    <div className="rounded-lg border border-border bg-muted/50 px-3 py-2 text-sm">
      <div className="flex items-center gap-2">
        <FileText className="h-4 w-4 flex-shrink-0 text-muted-foreground" />
        <span className="font-medium truncate">{attachment.filename}</span>
        <span className="text-muted-foreground text-xs whitespace-nowrap">
          {t("llm.attachment.chars", { count: attachment.char_count.toLocaleString() })}
        </span>
        <span className="text-muted-foreground text-xs whitespace-nowrap">
          {t("llm.attachment.estimatedTokens", { count: attachment.estimated_tokens.toLocaleString() })}
        </span>
        <button
          type="button"
          onClick={onRemove}
          disabled={removing}
          aria-label={t("llm.attachment.remove")}
          className="ml-auto flex-shrink-0 rounded p-0.5 hover:bg-muted transition-colors disabled:opacity-50"
        >
          {removing ? (
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          ) : (
            <X className="h-4 w-4 text-muted-foreground" />
          )}
        </button>
      </div>
      {attachment.preview && (
        <div className="mt-1.5">
          <span className="text-xs font-medium text-muted-foreground">{t("llm.attachment.preview")}: </span>
          <span className="text-xs text-muted-foreground line-clamp-2">{attachment.preview}</span>
        </div>
      )}
    </div>
  );
}
