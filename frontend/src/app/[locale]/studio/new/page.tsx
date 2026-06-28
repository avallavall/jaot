"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import {
  Sparkles,
  Blocks,
  Code2,
  Upload,
  LayoutTemplate,
  ShoppingBag,
  FilePlus,
} from "lucide-react";
import { useRouter } from "@/i18n/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { api } from "@/lib/api";
import { useBuilderStore } from "@/hooks/useBuilderStore";
import { getErrorMessage } from "@/lib/errors";

type TileKey =
  | "ai"
  | "visual"
  | "editor"
  | "import"
  | "template"
  | "marketplace"
  | "blank";

interface LauncherTile {
  key: TileKey;
  icon: ReactNode;
  label: string;
  desc: string;
  onClick: () => void;
}

/**
 * "New model" launcher. P0: every tile is present; only "Blank model" is wired
 * (it creates a model and drops into the workspace). The other starting points
 * are stubbed until their seeding flows land.
 */
export default function StudioNewPage() {
  const t = useTranslations("studio");
  const router = useRouter();
  const { activeWorkspaceId } = useAuth();
  const reset = useBuilderStore((s) => s.reset);
  const [creating, setCreating] = useState(false);

  const comingSoon = () => toast(t("comingSoon"));

  const handleBlank = async () => {
    if (creating) return;
    setCreating(true);
    try {
      reset();
      const doc = await api.createBuilderDocument(
        undefined,
        activeWorkspaceId ?? undefined
      );
      router.push(`/studio/${doc.id}/build`);
    } catch (err) {
      toast.error(getErrorMessage(err, t("createFailed")));
      setCreating(false);
    }
  };

  const tiles: LauncherTile[] = [
    { key: "ai", icon: <Sparkles className="h-6 w-6" />, label: t("tileAi"), desc: t("tileAiDesc"), onClick: comingSoon },
    { key: "visual", icon: <Blocks className="h-6 w-6" />, label: t("tileVisual"), desc: t("tileVisualDesc"), onClick: comingSoon },
    { key: "editor", icon: <Code2 className="h-6 w-6" />, label: t("tileEditor"), desc: t("tileEditorDesc"), onClick: comingSoon },
    { key: "import", icon: <Upload className="h-6 w-6" />, label: t("tileImport"), desc: t("tileImportDesc"), onClick: comingSoon },
    { key: "template", icon: <LayoutTemplate className="h-6 w-6" />, label: t("tileTemplate"), desc: t("tileTemplateDesc"), onClick: comingSoon },
    { key: "marketplace", icon: <ShoppingBag className="h-6 w-6" />, label: t("tileMarketplace"), desc: t("tileMarketplaceDesc"), onClick: comingSoon },
    { key: "blank", icon: <FilePlus className="h-6 w-6" />, label: t("tileBlank"), desc: t("tileBlankDesc"), onClick: handleBlank },
  ];

  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">{t("newModelTitle")}</h1>
        <p className="text-muted-foreground text-sm mt-1">
          {t("newModelSubtitle")}
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {tiles.map((tile) => (
          <button
            key={tile.key}
            onClick={tile.onClick}
            disabled={tile.key === "blank" && creating}
            className="text-left rounded-lg border p-5 bg-card hover:border-primary/50 hover:shadow-sm transition-all disabled:opacity-60 disabled:pointer-events-none"
          >
            <div className="text-primary mb-3">{tile.icon}</div>
            <h3 className="font-medium text-sm">{tile.label}</h3>
            <p className="text-xs text-muted-foreground mt-1">{tile.desc}</p>
          </button>
        ))}
      </div>
    </div>
  );
}
