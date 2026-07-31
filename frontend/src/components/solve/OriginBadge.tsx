"use client";

import { useTranslations } from "next-intl";

import {
  UNKNOWN_ORIGIN_CLASS,
  originLabel,
  resolveOriginKey,
  type OriginKey,
} from "@/lib/execution-origin";
import type { ExecutionSourceKind } from "@/lib/types";

interface OriginBadgeProps {
  origin?: string;
  /** When set to "model_project", the badge shows the studio-model style/label
   * regardless of the (looser) origin slug the async solve was tagged with. */
  sourceKind?: ExecutionSourceKind;
  triggerName?: string;
}

// Per-origin colour. Typed against ORIGIN_KEYS so adding an origin to the shared
// list is a type error here until it gets a style — the badge and the chart palette
// cannot drift apart. Unknown origins fall back to the neutral "manual" style.
const ORIGIN_STYLES = {
  manual:
    "bg-gray-100 text-gray-700 border-gray-200 dark:bg-gray-800/40 dark:text-gray-300 dark:border-gray-700",
  triggered:
    "bg-violet-100 text-violet-800 border-violet-200 dark:bg-violet-900/30 dark:text-violet-300 dark:border-violet-700",
  visual_builder:
    "bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-900/30 dark:text-blue-300 dark:border-blue-700",
  ai_builder:
    "bg-fuchsia-100 text-fuchsia-800 border-fuchsia-200 dark:bg-fuchsia-900/30 dark:text-fuchsia-300 dark:border-fuchsia-700",
  template:
    "bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-700",
  import:
    "bg-teal-100 text-teal-800 border-teal-200 dark:bg-teal-900/30 dark:text-teal-300 dark:border-teal-700",
  marketplace:
    "bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-300 dark:border-emerald-700",
  model_project:
    "bg-sky-100 text-sky-800 border-sky-200 dark:bg-sky-900/30 dark:text-sky-300 dark:border-sky-700",
  api: "bg-slate-100 text-slate-800 border-slate-200 dark:bg-slate-800/40 dark:text-slate-300 dark:border-slate-700",
  mcp: "bg-indigo-100 text-indigo-800 border-indigo-200 dark:bg-indigo-900/30 dark:text-indigo-300 dark:border-indigo-700",
} satisfies Record<OriginKey, string>;

export function OriginBadge({ origin, sourceKind, triggerName }: OriginBadgeProps) {
  const t = useTranslations("solve.origin");

  // Resolve once; the message keys match the ORIGIN_STYLES keys, so a single
  // typed t() call suffices. A studio ModelProject wins over the looser origin
  // slug the async solve carried.
  const resolved: OriginKey | null = resolveOriginKey(origin, sourceKind);
  const title =
    resolved === "triggered"
      ? triggerName
        ? t("triggerName", { name: triggerName })
        : t("triggeredRun")
      : undefined;
  // A slug this build does not know is shown as it was stored: the reference
  // database holds rows tagged `cron`, which today's sanitiser would never write,
  // and calling those "Manual" is a label the data does not support.
  const label = originLabel(origin, sourceKind, t);
  // Unknown slugs get their own muted style so the pale slice they take in a
  // chart is recognisable in the list beside it, instead of reading as manual.
  const style = resolved
    ? ORIGIN_STYLES[resolved]
    : origin
      ? UNKNOWN_ORIGIN_CLASS
      : ORIGIN_STYLES.manual;

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${style}`}
      title={title}
    >
      {label}
    </span>
  );
}
