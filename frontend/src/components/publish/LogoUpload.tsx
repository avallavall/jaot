"use client";

import { useState, useRef } from "react";
import { Package, X, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp"];
const MAX_SIZE = 2 * 1024 * 1024; // 2MB

interface LogoUploadProps {
  modelId: string;
  logoUrl: string | null;
  onLogoChange: (url: string | null) => void;
  disabled?: boolean;
}

export function LogoUpload({ modelId, logoUrl, onLogoChange, disabled }: LogoUploadProps) {
  const t = useTranslations("solve.publish");
  const tError = useTranslations("errors.codes");
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleClick = () => {
    if (disabled || uploading) return;
    fileInputRef.current?.click();
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Reset input so same file can be re-selected
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

    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);

      // Send the header only when there is a key. Interpolating a null produced
      // the literal string "Bearer null" on every cookie session, which is what
      // this request has been sending for most users; the server ignored it and
      // authenticated from the cookie, so it worked while reading as a bug.
      const key = api.getApiKey();
      const res = await fetch(`/api/v2/models/catalog/${modelId}/logo`, {
        method: "POST",
        headers: key ? { Authorization: `Bearer ${key}` } : {},
        body: formData,
        credentials: "include",
      });

      if (!res.ok) {
        // This route is called with fetch, not the api client, so the refusal has
        // to be read here. Two of them mean different things to the author: the
        // instance stores no images at all, or this file is not one.
        const body = await res.json().catch(() => null);
        const code = body?.code as string | undefined;
        throw new Error(
          code && tError.has(code) ? tError(code) : body?.detail || t("logoUploadFailed"),
        );
      }

      const data = await res.json();
      onLogoChange(data.url);
    } catch (err) {
      // It said "Uploading image..." — the progress label — on every failure.
      toast.error(err instanceof Error ? err.message : t("logoUploadFailed"));
    } finally {
      setUploading(false);
    }
  };

  const handleRemove = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await api.request(`/api/v2/models/catalog/${modelId}/logo`, { method: "DELETE" });
      onLogoChange(null);
    } catch {
      // It named the sections, which this button does not touch.
      toast.error(t("logoRemoveFailed"));
    }
  };

  return (
    <div>
      <p className="text-sm font-medium mb-2">{t("uploadLogo")}</p>
      <div
        onClick={handleClick}
        className={cn(
          "relative w-32 h-32 rounded-lg border-2 border-dashed flex items-center justify-center overflow-hidden group",
          disabled
            ? "cursor-default opacity-50"
            : "cursor-pointer hover:border-primary transition-colors"
        )}
      >
        {uploading && (
          <div className="absolute inset-0 bg-background/70 flex items-center justify-center z-10">
            <Loader2 className="size-6 animate-spin text-primary" />
          </div>
        )}

        {logoUrl ? (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={logoUrl}
              alt="Model logo"
              className="w-full h-full object-cover"
            />
            {!disabled && (
              <button
                type="button"
                onClick={handleRemove}
                className="absolute top-1 right-1 bg-destructive text-destructive-foreground rounded-full p-0.5 opacity-0 group-hover:opacity-100 transition-opacity z-10"
                title={t("removeLogo")}
              >
                <X className="size-3.5" />
              </button>
            )}
          </>
        ) : (
          <div className="flex flex-col items-center gap-1 text-muted-foreground">
            <Package className="size-8" />
            <span className="text-xs">{t("uploadLogo")}</span>
          </div>
        )}

        <input
          ref={fileInputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          onChange={handleFileSelect}
          className="hidden"
          disabled={disabled}
        />
      </div>
      <p className="text-xs text-muted-foreground mt-1">{t("uploadLogoHelp")}</p>
    </div>
  );
}
