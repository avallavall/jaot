"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { NodePalette } from "@/components/builder/NodePalette";
import { PropertiesPanel } from "@/components/builder/PropertiesPanel";
import { useBuilderStore } from "@/hooks/useBuilderStore";

// ReactFlow requires browser APIs — load the canvas client-side only.
const BuilderCanvas = dynamic(
  () =>
    import("@/components/builder/BuilderCanvas").then((m) => m.BuilderCanvas),
  { ssr: false }
);

const SUB_LENSES = ["canvas", "assistant", "editor"] as const;
type SubLens = (typeof SUB_LENSES)[number];

/**
 * The Build lens. P0 wires the existing visual Canvas; the Assistant (AI chat)
 * and Editor (DSL/text) sub-lenses are placeholders until their slices land.
 */
export function BuildPanel() {
  const t = useTranslations("studio");
  const [lens, setLens] = useState<SubLens>("canvas");
  const selectedNodeId = useBuilderStore((s) => s.selectedNodeId);

  const labels: Record<SubLens, string> = {
    canvas: t("subLensCanvas"),
    assistant: t("subLensAssistant"),
    editor: t("subLensEditor"),
  };

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="flex items-center gap-1 px-3 py-1.5 border-b">
        {SUB_LENSES.map((l) => (
          <button
            key={l}
            onClick={() => setLens(l)}
            aria-pressed={lens === l}
            className={cn(
              "px-3 py-1 text-sm rounded-md transition-colors",
              lens === l
                ? "bg-muted font-medium text-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {labels[l]}
          </button>
        ))}
      </div>

      {lens === "canvas" ? (
        <div className="flex flex-1 min-h-0 overflow-hidden">
          <NodePalette />
          <BuilderCanvas />
          {selectedNodeId && <PropertiesPanel />}
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center p-6 text-center text-sm text-muted-foreground">
          {t("subLensComingSoon")}
        </div>
      )}
    </div>
  );
}
