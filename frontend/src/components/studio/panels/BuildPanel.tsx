"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { useTranslations } from "next-intl";
import { LayoutGrid } from "lucide-react";
import { cn } from "@/lib/utils";
import { NodePalette } from "@/components/builder/NodePalette";
import { PropertiesPanel } from "@/components/builder/PropertiesPanel";
import { useBuilderStore } from "@/hooks/useBuilderStore";
import { useModelProjectStore } from "../store/useModelProjectStore";
import { useDslStatus } from "@/hooks/useDslStatus";
import { modelElementCount } from "../store/model-scale";
import { TooLargeNotice } from "../TooLargeNotice";
import { ModelEditorPanel } from "./editor/ModelEditorPanel";
import { JModelEditorPanel } from "./jmodel/JModelEditorPanel";

// ReactFlow requires browser APIs — load the canvas client-side only.
const BuilderCanvas = dynamic(
  () =>
    import("@/components/builder/BuilderCanvas").then((m) => m.BuilderCanvas),
  { ssr: false }
);

// The AI chat is client-only (SSE streaming + uploads); lazy-load it.
const AssistantLens = dynamic(
  () => import("./assistant/AssistantLens").then((m) => m.AssistantLens),
  { ssr: false }
);

const SUB_LENSES = ["canvas", "assistant", "editor", "jmodel"] as const;
type SubLens = (typeof SUB_LENSES)[number];

function isSubLens(value: string | null): value is SubLens {
  return value !== null && (SUB_LENSES as readonly string[]).includes(value);
}

/**
 * The Build lens. Sub-lenses: Canvas (visual), Assistant (AI chat), Editor
 * (model-as-JSON text), and — when the JAOT_DSL feature is on — JModel (the DSL editor).
 * The active sub-lens is local UI state, but a `?lens=` query selects the initial one
 * (so a launcher tile can open straight into a specific lens).
 */
export function BuildPanel() {
  const t = useTranslations("studio");
  const dslEnabled = useDslStatus();
  const [lens, setLens] = useState<SubLens>("canvas");
  const selectedNodeId = useBuilderStore((s) => s.selectedNodeId);
  const canvasDisabled = useModelProjectStore((s) => s.canvasDisabled);
  const elementCount = useModelProjectStore((s) => modelElementCount(s.problem));

  // Apply an initial `?lens=` after mount (client-only) — kept out of the SSR pass
  // so server/first-render stay "canvas" and there is no hydration mismatch.
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("lens");
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (isSubLens(q)) setLens(q);
  }, []);

  // The JModel lens is only offered when the JAOT_DSL feature is enabled.
  const visibleLenses = dslEnabled
    ? SUB_LENSES
    : SUB_LENSES.filter((l) => l !== "jmodel");

  const labels: Record<SubLens, string> = {
    canvas: t("subLensCanvas"),
    assistant: t("subLensAssistant"),
    editor: t("subLensEditor"),
    jmodel: t("subLensJModel"),
  };

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="flex items-center gap-1 px-3 py-1.5 border-b">
        {visibleLenses.map((l) => (
          <button
            key={l}
            onClick={() => setLens(l)}
            data-testid={`studio-sublens-${l}`}
            aria-pressed={lens === l}
            className={cn(
              "inline-flex items-center gap-1.5 px-3 py-1 text-sm rounded-md transition-colors",
              lens === l
                ? "bg-muted font-medium text-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {labels[l]}
          </button>
        ))}
      </div>

      {lens === "canvas" && canvasDisabled ? (
        <TooLargeNotice
          testid="studio-canvas-too-large"
          icon={<LayoutGrid className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />}
          title={t("canvasTooLargeTitle")}
          body={t("canvasTooLarge", { count: elementCount })}
        />
      ) : lens === "editor" ? (
        <ModelEditorPanel />
      ) : lens === "jmodel" && dslEnabled ? (
        <JModelEditorPanel />
      ) : lens === "assistant" ? (
        <AssistantLens />
      ) : (
        // Canvas view — also the fallback when "jmodel" is selected but disabled.
        <div className="flex flex-1 min-h-0 overflow-hidden">
          <NodePalette />
          <BuilderCanvas />
          {selectedNodeId && <PropertiesPanel />}
        </div>
      )}
    </div>
  );
}
