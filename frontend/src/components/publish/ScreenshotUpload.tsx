"use client";

import { useState, useRef } from "react";
import { Plus, X, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp"];
const MAX_SIZE = 2 * 1024 * 1024; // 2MB
const MAX_SCREENSHOTS = 6;

interface ScreenshotUploadProps {
  modelId: string;
  screenshots: string[];
  onScreenshotsChange: (urls: string[]) => void;
  disabled?: boolean;
}

export function ScreenshotUpload({
  modelId,
  screenshots,
  onScreenshotsChange,
  disabled,
}: ScreenshotUploadProps) {
  const t = useTranslations("solve.publish");
  const [uploadingIndex, setUploadingIndex] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleAddClick = () => {
    if (disabled || uploadingIndex !== null) return;
    fileInputRef.current?.click();
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Reset input
    e.target.value = "";

    // Client-side validation
    if (!ALLOWED_TYPES.includes(file.type)) {
      toast.error(t("invalidImageType"));
      return;
    }
    if (file.size > MAX_SIZE) {
      toast.error(t("imageTooLarge"));
      return;
    }

    setUploadingIndex(screenshots.length);
    try {
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetch(`/api/v2/models/catalog/${modelId}/screenshots`, {
        method: "POST",
        headers: { Authorization: `Bearer ${api.getApiKey()}` },
        body: formData,
        credentials: "include",
      });

      if (!res.ok) {
        throw new Error(`Upload failed (${res.status})`);
      }

      const data = await res.json();
      onScreenshotsChange(data.screenshots);
    } catch {
      toast.error(t("uploadingImage"));
    } finally {
      setUploadingIndex(null);
    }
  };

  const handleRemove = async (index: number) => {
    try {
      const res = await api.request<{ screenshots: string[] }>(
        `/api/v2/models/catalog/${modelId}/screenshots/${index}`,
        { method: "DELETE" }
      );
      onScreenshotsChange(res.screenshots);
    } catch {
      toast.error(t("sectionsSaveFailed"));
    }
  };

  return (
    <div className="flex-1">
      <p className="text-sm font-medium mb-2">{t("screenshots")}</p>
      <p className="text-xs text-muted-foreground mb-3">{t("screenshotsHelp")}</p>
      <div
        className={cn(
          "grid grid-cols-2 md:grid-cols-3 gap-3",
          disabled && "opacity-50"
        )}
      >
        {screenshots.map((url, idx) => (
          <div
            key={url}
            className="relative aspect-video rounded-lg border overflow-hidden group"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={url}
              alt={`Screenshot ${idx + 1}`}
              className="w-full h-full object-cover"
            />
            {!disabled && (
              <button
                type="button"
                onClick={() => handleRemove(idx)}
                className="absolute top-1 right-1 bg-destructive text-destructive-foreground rounded-full p-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
                title={t("removeScreenshot")}
              >
                <X className="size-3.5" />
              </button>
            )}
          </div>
        ))}

        {uploadingIndex !== null && (
          <div className="aspect-video rounded-lg border-2 border-dashed flex items-center justify-center">
            <Loader2 className="size-6 animate-spin text-primary" />
          </div>
        )}

        {!disabled && screenshots.length < MAX_SCREENSHOTS && uploadingIndex === null && (
          <div
            onClick={handleAddClick}
            className="aspect-video rounded-lg border-2 border-dashed flex flex-col items-center justify-center gap-1 cursor-pointer hover:border-primary transition-colors text-muted-foreground hover:text-foreground"
          >
            <Plus className="size-6" />
            <span className="text-xs">{t("addScreenshot")}</span>
          </div>
        )}
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        onChange={handleFileSelect}
        className="hidden"
        disabled={disabled}
      />
    </div>
  );
}
