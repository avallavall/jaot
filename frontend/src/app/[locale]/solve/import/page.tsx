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
import { SolverSelect } from "@/components/solve/SolverSelect";
import { PreviewStat } from "@/components/solve/PreviewStat";
import { useSolvers } from "@/hooks/useSolvers";
import {
  Upload,
  FileUp,
  FileText,
  AlertCircle,
  Loader2,
  X,
  ArrowLeft,
  ArrowRight,
} from "lucide-react";

type PageStep = "upload" | "preview" | "importing";

export default function FileImportPage() {
  const t = useTranslations("solve.import");

  const router = useRouter();

  const [step, setStep] = useState<PageStep>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<FileImportPreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { solverName, setSolverName, availableSolvers, solversLoading } = useSolvers();

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
      const result = await api.fileImport.import(file, solverName);
      toast.success(t("importSuccess", { name: file.name }));
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
  }, [file, t, router, solverName]);

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="mb-8">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => router.push("/solve")}
          className="mb-4 -ml-2"
        >
          <ArrowLeft className="h-4 w-4 mr-1" />
          {t("backToModels")}
        </Button>
        <h1 className="text-3xl font-bold text-foreground mb-2 flex items-center gap-3">
          <FileUp className="h-8 w-8 text-primary" />
          {t("pageTitle")}
        </h1>
        <p className="text-muted-foreground">{t("pageDescription")}</p>
      </div>

      {error && (
        <div className="flex items-start gap-2 p-4 mb-6 text-sm bg-destructive/10 text-destructive rounded-lg">
          <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Step: Upload */}
      {step === "upload" && (
        <div className="max-w-xl mx-auto">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`flex flex-col items-center justify-center gap-4 p-12 border-2 border-dashed rounded-lg cursor-pointer transition-colors ${
              dragOver
                ? "border-primary bg-primary/5"
                : "border-border hover:border-primary/50 hover:bg-muted/30"
            }`}
            data-testid="file-drop-zone"
          >
            <Upload className="h-12 w-12 text-muted-foreground" />
            <div className="text-center">
              <p className="text-base font-medium">{t("dropOrClick")}</p>
              <p className="text-sm text-muted-foreground mt-2">
                {t("acceptedFormats", { formats: ACCEPTED_EXTENSIONS.join(", ") })}
              </p>
              <p className="text-sm text-muted-foreground">
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
            <div className="flex items-center justify-between p-4 mt-4 bg-muted/30 border border-border rounded-lg">
              <div className="flex items-center gap-3 min-w-0">
                <FileText className="h-5 w-5 text-primary flex-shrink-0" />
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">{file.name}</p>
                  <p className="text-xs text-muted-foreground">{formatFileSize(file.size)}</p>
                </div>
              </div>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={(e) => {
                  e.stopPropagation();
                  setFile(null);
                  setError(null);
                }}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          )}

          <div className="flex justify-end mt-6">
            <Button onClick={handlePreview} disabled={!file || loading} size="lg">
              {loading && <Loader2 className="h-4 w-4 animate-spin" />}
              {t("preview")}
              <ArrowRight className="h-4 w-4 ml-1" />
            </Button>
          </div>
        </div>
      )}

      {/* Step: Preview */}
      {step === "preview" && preview && (
        <div className="max-w-xl mx-auto">
          <div className="bg-card border border-border rounded-lg p-6">
            <h2 className="text-lg font-semibold mb-4">{t("previewTitle")}</h2>

            <div className="grid grid-cols-2 gap-4 mb-4">
              <PreviewStat
                label={t("format")}
                value={preview.metadata.source_format.toUpperCase()}
              />
              <PreviewStat label={t("variables")} value={String(preview.metadata.num_variables)} />
              <PreviewStat
                label={t("constraints")}
                value={String(preview.metadata.num_constraints)}
              />
              <PreviewStat
                label={t("objectiveType")}
                value={preview.problem.objective.sense}
              />
            </div>

            {file && (
              <div className="flex items-center gap-2 p-3 bg-muted/20 border border-border rounded-md mb-4">
                <FileText className="h-4 w-4 text-primary" />
                <span className="text-sm font-medium">{file.name}</span>
                <span className="text-xs text-muted-foreground">({formatFileSize(file.size)})</span>
              </div>
            )}

            <PreviewStat
              label={t("estimatedCredits")}
              value={String(preview.metadata.estimated_credits)}
            />
          </div>

          <SolverSelect
            id="import-solver-select"
            solverName={solverName}
            onSolverChange={setSolverName}
            availableSolvers={availableSolvers}
            loading={solversLoading}
          />

          <div className="flex justify-between mt-6">
            <Button
              variant="outline"
              onClick={() => {
                setStep("upload");
                setPreview(null);
              }}
            >
              <ArrowLeft className="h-4 w-4 mr-1" />
              {t("back")}
            </Button>
            <Button onClick={handleSolve} disabled={loading} size="lg">
              {loading && <Loader2 className="h-4 w-4 animate-spin" />}
              {t("importAndSolve")}
            </Button>
          </div>
        </div>
      )}

      {/* Step: Importing */}
      {step === "importing" && (
        <div className="flex flex-col items-center gap-4 py-16">
          <Loader2 className="h-10 w-10 animate-spin text-primary" />
          <p className="text-muted-foreground">{t("importing")}</p>
        </div>
      )}
    </div>
  );
}
