"use client";

import { useState, useCallback, useRef } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { api } from "@/lib/api";
import type { FileImportPreviewResponse } from "@/lib/types";
import {
  ACCEPTED_EXTENSIONS,
  MAX_FILE_SIZE_MB,
  MAX_FILE_SIZE_BYTES,
  isAcceptedFile,
  formatFileSize,
} from "@/lib/file-import";
import { getErrorMessage } from "@/lib/errors";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { PreviewStat } from "@/components/solve/PreviewStat";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Upload, FileUp, FileText, AlertCircle, Loader2, X } from "lucide-react";

interface FileImportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type DialogStep = "upload" | "preview" | "importing";

export function FileImportDialog({ open, onOpenChange }: FileImportDialogProps) {
  const t = useTranslations("solve.import");
  const router = useRouter();

  const [step, setStep] = useState<DialogStep>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<FileImportPreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const reset = useCallback(() => {
    setStep("upload");
    setFile(null);
    setDragOver(false);
    setError(null);
    setPreview(null);
    setLoading(false);
  }, []);

  const handleClose = useCallback(
    (open: boolean) => {
      if (!open) reset();
      onOpenChange(open);
    },
    [onOpenChange, reset],
  );

  const validateAndSetFile = useCallback(
    (selected: File) => {
      setError(null);

      if (!isAcceptedFile(selected)) {
        setError(t("invalidFormat", { formats: ACCEPTED_EXTENSIONS.join(", ") }));
        return;
      }

      if (selected.size > MAX_FILE_SIZE_BYTES) {
        setError(t("fileTooLarge", { max: MAX_FILE_SIZE_MB }));
        return;
      }

      setFile(selected);
    },
    [t],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const dropped = e.dataTransfer.files[0];
      if (dropped) validateAndSetFile(dropped);
    },
    [validateAndSetFile],
  );

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selected = e.target.files?.[0];
      if (selected) validateAndSetFile(selected);
      // Reset input so re-selecting the same file triggers onChange
      e.target.value = "";
    },
    [validateAndSetFile],
  );

  const handlePreview = useCallback(async () => {
    if (!file) return;
    setLoading(true);
    setError(null);

    try {
      const result = await api.fileImport.preview(file);
      setPreview(result);
      setStep("preview");
    } catch (err) {
      setError(getErrorMessage(err, t("previewFailed")));
    } finally {
      setLoading(false);
    }
  }, [file, t]);

  const handleSolve = useCallback(async () => {
    if (!file) return;
    setStep("importing");
    setLoading(true);
    setError(null);

    try {
      const result = await api.fileImport.import(file);
      toast.success(t("importSuccess", { name: file.name }));
      handleClose(false);
      if (result.execution_id) {
        router.push(`/solve/executions/${result.execution_id}`);
      } else {
        router.push("/solve/executions");
      }
    } catch (err) {
      setError(getErrorMessage(err, t("importFailed")));
      setStep("preview");
    } finally {
      setLoading(false);
    }
  }, [file, t, handleClose, router]);

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileUp className="h-5 w-5 text-primary" />
            {t("title")}
          </DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>

        {error && (
          <div className="flex items-start gap-2 p-3 text-sm bg-destructive/10 text-destructive rounded-md">
            <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Step: Upload */}
        {step === "upload" && (
          <>
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`flex flex-col items-center justify-center gap-3 p-8 border-2 border-dashed rounded-lg cursor-pointer transition-colors ${
                dragOver
                  ? "border-primary bg-primary/5"
                  : "border-border hover:border-primary/50 hover:bg-muted/30"
              }`}
              data-testid="file-drop-zone"
            >
              <Upload className="h-8 w-8 text-muted-foreground" />
              <div className="text-center">
                <p className="text-sm font-medium">{t("dropOrClick")}</p>
                <p className="text-xs text-muted-foreground mt-1">
                  {t("acceptedFormats", { formats: ACCEPTED_EXTENSIONS.join(", ") })}
                </p>
                <p className="text-xs text-muted-foreground">
                  {t("maxSize", { size: MAX_FILE_SIZE_MB })}
                </p>
              </div>
              <input
                ref={fileInputRef}
                type="file"
                accept={ACCEPTED_EXTENSIONS.join(",")}
                onChange={handleFileInput}
                className="hidden"
                data-testid="file-input"
              />
            </div>

            {file && (
              <div className="flex items-center justify-between p-3 bg-muted/30 border border-border rounded-md">
                <div className="flex items-center gap-2 min-w-0">
                  <FileText className="h-4 w-4 text-primary flex-shrink-0" />
                  <div className="min-w-0">
                    <p className="text-sm font-medium truncate">{file.name}</p>
                    <p className="text-xs text-muted-foreground">{formatFileSize(file.size)}</p>
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  onClick={(e) => {
                    e.stopPropagation();
                    setFile(null);
                    setError(null);
                  }}
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              </div>
            )}

            <DialogFooter>
              <Button variant="outline" onClick={() => handleClose(false)}>
                {t("cancel")}
              </Button>
              <Button onClick={handlePreview} disabled={!file || loading}>
                {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                {t("preview")}
              </Button>
            </DialogFooter>
          </>
        )}

        {/* Step: Preview */}
        {step === "preview" && preview && (
          <>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <PreviewStat
                  label={t("format")}
                  value={preview.metadata.source_format.toUpperCase()}
                />
                <PreviewStat
                  label={t("variables")}
                  value={String(preview.metadata.num_variables)}
                />
                <PreviewStat
                  label={t("constraints")}
                  value={String(preview.metadata.num_constraints)}
                />
                <PreviewStat
                  label={t("objectiveType")}
                  value={preview.problem.objective.sense}
                />
              </div>
              <PreviewStat
                label={t("estimatedCredits")}
                value={String(preview.metadata.estimated_credits)}
              />
            </div>

            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  setStep("upload");
                  setPreview(null);
                }}
              >
                {t("back")}
              </Button>
              <Button onClick={handleSolve} disabled={loading}>
                {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                {t("importAndSolve")}
              </Button>
            </DialogFooter>
          </>
        )}

        {/* Step: Importing */}
        {step === "importing" && (
          <div className="flex flex-col items-center gap-3 py-6">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <p className="text-sm text-muted-foreground">{t("importing")}</p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
