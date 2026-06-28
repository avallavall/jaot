"use client";

import { useParams, notFound } from "next/navigation";
import { BuildPanel } from "@/components/studio/panels/BuildPanel";
import { AnalyzePanel } from "@/components/studio/panels/AnalyzePanel";
import { SolvePanel } from "@/components/studio/panels/SolvePanel";

const TAB_REGISTRY = {
  build: BuildPanel,
  analyze: AnalyzePanel,
  solve: SolvePanel,
} as const;

type StudioTab = keyof typeof TAB_REGISTRY;

/**
 * Renders the active workspace lens for a validated `tab` segment.
 * Unknown tabs 404 (so `/studio/<id>/foo` is not a silent blank page).
 */
export default function StudioTabPage() {
  const params = useParams<{ tab: string }>();
  const tab = params?.tab ?? "";

  if (!(tab in TAB_REGISTRY)) {
    notFound();
  }

  const Panel = TAB_REGISTRY[tab as StudioTab];
  return <Panel />;
}
