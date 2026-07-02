"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import {
  Sparkles,
  Blocks,
  Code2,
  Braces,
  Upload,
  LayoutTemplate,
  ShoppingBag,
  FilePlus,
} from "lucide-react";
import { useRouter } from "@/i18n/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { api } from "@/lib/api";
import { useBuilderStore } from "@/hooks/useBuilderStore";
import { useDslStatus } from "@/hooks/useDslStatus";
import { getErrorMessage } from "@/lib/errors";
import { cn } from "@/lib/utils";
import { importFileToProject } from "@/components/studio/import-launch";

type TileKey =
  | "ai"
  | "visual"
  | "editor"
  | "jmodel"
  | "import"
  | "template"
  | "marketplace"
  | "blank";

interface LauncherTile {
  key: TileKey;
  icon: ReactNode;
  label: string;
  desc: string;
  /** false → rendered as a clearly-disabled "Soon" tile (no click). */
  available: boolean;
  onClick?: () => void;
}

/**
 * "New model" launcher. Only the implemented starting points — Blank model and
 * Visual canvas (both create a model and open the visual Build tab) — are clickable.
 * The not-yet-built tiles (AI / Editor / Import / Template / Marketplace) render as
 * visibly-disabled "Soon" cards instead of active controls that toast "coming soon".
 */
export default function StudioNewPage() {
  const t = useTranslations("studio");
  const router = useRouter();
  const { activeWorkspaceId } = useAuth();
  const reset = useBuilderStore((s) => s.reset);
  const dslEnabled = useDslStatus();
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const busy = creating || importing;

  const handleCreate = async (initialLens?: "editor" | "assistant" | "jmodel") => {
    if (busy) return;
    setCreating(true);
    try {
      reset();
      const project = await api.createProject(
        { name: "Untitled Model", workspace_id: activeWorkspaceId ?? undefined },
        activeWorkspaceId ?? undefined
      );
      const suffix = initialLens ? `?lens=${initialLens}` : "";
      router.push(`/studio/${project.id}/build${suffix}`);
    } catch (err) {
      toast.error(getErrorMessage(err, t("createFailed")));
      setCreating(false);
    }
  };

  const handleImportClick = () => {
    if (busy) return;
    const input = document.getElementById("studio-import-file");
    if (input instanceof HTMLInputElement) input.click();
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file
    if (!file) return;
    setImporting(true);
    try {
      const projectId = await importFileToProject(file, activeWorkspaceId ?? undefined);
      router.push(`/studio/${projectId}/solve`);
    } catch (err) {
      toast.error(getErrorMessage(err, t("importFailed")));
      setImporting(false);
    }
  };

  const tiles: LauncherTile[] = [
    { key: "ai", icon: <Sparkles className="h-6 w-6" />, label: t("tileAi"), desc: t("tileAiDesc"), available: true, onClick: () => handleCreate("assistant") },
    { key: "visual", icon: <Blocks className="h-6 w-6" />, label: t("tileVisual"), desc: t("tileVisualDesc"), available: true, onClick: () => handleCreate() },
    { key: "editor", icon: <Code2 className="h-6 w-6" />, label: t("tileEditor"), desc: t("tileEditorDesc"), available: true, onClick: () => handleCreate("editor") },
    { key: "jmodel", icon: <Braces className="h-6 w-6" />, label: t("tileJModel"), desc: t("tileJModelDesc"), available: dslEnabled, onClick: () => handleCreate("jmodel") },
    { key: "import", icon: <Upload className="h-6 w-6" />, label: t("tileImport"), desc: t("tileImportDesc"), available: true, onClick: handleImportClick },
    { key: "template", icon: <LayoutTemplate className="h-6 w-6" />, label: t("tileTemplate"), desc: t("tileTemplateDesc"), available: true, onClick: () => router.push("/studio/templates") },
    { key: "marketplace", icon: <ShoppingBag className="h-6 w-6" />, label: t("tileMarketplace"), desc: t("tileMarketplaceDesc"), available: true, onClick: () => router.push("/marketplace") },
    { key: "blank", icon: <FilePlus className="h-6 w-6" />, label: t("tileBlank"), desc: t("tileBlankDesc"), available: true, onClick: () => handleCreate() },
  ];

  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">{t("newModelTitle")}</h1>
        <p className="text-muted-foreground text-sm mt-1">{t("newModelSubtitle")}</p>
      </div>

      <input
        id="studio-import-file"
        type="file"
        accept=".mps,.lp,.cip,.json,.gz"
        className="hidden"
        aria-hidden="true"
        tabIndex={-1}
        onChange={handleFileChange}
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {tiles.map((tile) =>
          tile.available ? (
            <button
              key={tile.key}
              data-testid={`launcher-tile-${tile.key}`}
              onClick={tile.onClick}
              disabled={busy}
              className="text-left rounded-lg border p-5 bg-card hover:border-primary/50 hover:shadow-sm transition-all disabled:opacity-60 disabled:pointer-events-none"
            >
              <div className="text-primary mb-3">{tile.icon}</div>
              <h3 className="font-medium text-sm">
                {importing && tile.key === "import" ? t("importing") : tile.label}
              </h3>
              <p className="text-xs text-muted-foreground mt-1">{tile.desc}</p>
            </button>
          ) : (
            <div
              key={tile.key}
              data-testid={`launcher-tile-${tile.key}`}
              aria-disabled="true"
              className={cn(
                "relative text-left rounded-lg border p-5 bg-muted/20 cursor-not-allowed select-none"
              )}
            >
              <span className="absolute top-3 right-3 rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                {t("soon")}
              </span>
              <div className="text-muted-foreground/60 mb-3">{tile.icon}</div>
              <h3 className="font-medium text-sm text-muted-foreground">{tile.label}</h3>
              <p className="text-xs text-muted-foreground/80 mt-1">{tile.desc}</p>
            </div>
          )
        )}
      </div>
    </div>
  );
}
