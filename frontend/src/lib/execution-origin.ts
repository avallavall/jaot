/**
 * Where a solve came from: the origin slugs, how to label and colour them, and
 * how to navigate back to the object that produced one.
 *
 * The slug list mirrors `VALID_ORIGINS` in
 * `app/shared/constants/execution_provenance.py`, pinned by a test. Today's writers
 * all sanitise against that set, but the column predates them: the reference
 * database holds rows tagged `cron`, which nothing would write now. So a slug off
 * the list is a real case, not a hypothetical — see `resolveOriginKey`.
 * `model_project` is not an origin: it is the `source_kind` the studio shows in
 * place of the looser origin the universal async solve tags its runs with.
 *
 * Every surface that shows an origin to a person reads from here. Three of them
 * used to hardcode "manual vs triggered" instead, which is how the analytics
 * legend ended up printing "Automatic" three times in one chart — and calling
 * studio runs automatic when they are launched by hand.
 */

/**
 * The kind of object an execution can navigate back to. Mirrors the backend's
 * `VALID_SOURCE_KINDS`. It lives here, beside the origin slugs, because the one
 * rule that needs both is the studio precedence below — and `types.ts` re-exports
 * it, so consumers still import it from the barrel.
 */
export type ExecutionSourceKind =
  | "builder_document"
  | "llm_conversation"
  | "template"
  | "organization_model"
  | "trigger"
  | "imported_file"
  // P1a: a solve launched from a first-class ModelProject. The badge and the
  // back-link both give this precedence over the looser origin slug the
  // universal async solve tags studio runs with.
  | "model_project";

export const ORIGIN_KEYS = [
  "manual",
  "visual_builder",
  "ai_builder",
  "template",
  "import",
  "marketplace",
  "triggered",
  "api",
  "mcp",
  "model_project",
  // One column of a solver comparison. Its own slug because a comparison writes
  // one execution per solver: four rows land in history for a single thing the
  // user did, and without a label they read as four separate solves.
  "comparison",
] as const;

export type OriginKey = (typeof ORIGIN_KEYS)[number];

/** Narrows a persisted slug to one this frontend knows how to label. */
export function isOriginKey(value: string | null | undefined): value is OriginKey {
  return value != null && (ORIGIN_KEYS as readonly string[]).includes(value);
}

/**
 * Resolves what a row should be shown as: the studio's `source_kind` wins over the
 * looser origin slug. The single place that rule is written — `executionOriginHref`
 * calls this rather than repeating it, so the label and the back-link cannot come
 * to disagree about what a studio run is.
 *
 * Returns `null` for a slug this build does not know, so a distribution chart can
 * keep it as its own slice instead of folding it into "manual" and inflating that
 * count, and a badge can show it as stored instead of naming it wrongly.
 */
export function resolveOriginKey(
  origin: string | null | undefined,
  sourceKind?: ExecutionSourceKind | null
): OriginKey | null {
  if (sourceKind === "model_project") return "model_project";
  return isOriginKey(origin) ? origin : null;
}

/**
 * Chart-safe hex per origin, one tone family per origin as in `OriginBadge`'s
 * Tailwind classes — a legend and a badge for the same run should not disagree on
 * colour. `api` sits on slate-600 rather than slate-500 so it stays apart from
 * manual's gray-500 when both are slices of the same donut.
 */
export const ORIGIN_CHART_COLORS: Record<OriginKey, string> = {
  manual: "#6b7280",
  visual_builder: "#3b82f6",
  ai_builder: "#d946ef",
  template: "#f59e0b",
  import: "#14b8a6",
  marketplace: "#10b981",
  triggered: "#8b5cf6",
  api: "#475569",
  mcp: "#6366f1",
  model_project: "#0ea5e9",
  comparison: "#f43f5e",
};

/** Reserved for slugs `ORIGIN_KEYS` does not cover — paler than every real one. */
export const UNKNOWN_ORIGIN_COLOR = "#d1d5db";

/**
 * The badge equivalent of `UNKNOWN_ORIGIN_COLOR`. Without it an unknown slug
 * rendered in manual's own grey, so the pale slice in a chart had no counterpart
 * in the list beside it — the disagreement the palette comment above rules out.
 */
export const UNKNOWN_ORIGIN_CLASS =
  "bg-gray-50 text-gray-500 border-gray-200 border-dashed " +
  "dark:bg-gray-900/40 dark:text-gray-400 dark:border-gray-700";

/**
 * The name to show for one run's origin: the translated label when the slug is
 * known, the slug itself when it is not, and "manual" only when nothing was
 * recorded (the backend's own default).
 *
 * Shared because the badge and the exported report were resolving it with two
 * copies of the same three lines, and a copy is how the surfaces drifted apart in
 * the first place. `t` takes the caller's `useTranslations("solve.origin")`.
 */
export function originLabel(
  origin: string | null | undefined,
  sourceKind: ExecutionSourceKind | null | undefined,
  t: (key: OriginKey) => string
): string {
  const resolved = resolveOriginKey(origin, sourceKind);
  if (resolved) return t(resolved);
  // Truthiness, not `??`: an empty string is not a name either.
  return origin || t("manual");
}

export interface OriginSlice {
  name: string;
  value: number;
  fill: string;
}

/**
 * Turns the backend's `{origin: count}` map into chart slices, largest first.
 *
 * Lives here rather than in the analytics page because this mapping *is* the
 * defect that was reported: the page folded eight origins into one label and one
 * colour. As a function it can be asserted directly — a known slug takes its
 * translated label, an unknown one keeps the name it was stored under, and
 * neither is merged into another.
 */
export function buildOriginSlices(
  counts: Record<string, number>,
  label: (key: OriginKey) => string
): OriginSlice[] {
  return Object.entries(counts)
    .map(([name, value]) => ({
      name: isOriginKey(name) ? label(name) : name,
      value,
      fill: isOriginKey(name) ? ORIGIN_CHART_COLORS[name] : UNKNOWN_ORIGIN_COLOR,
    }))
    .sort((a, b) => b.value - a.value);
}

/**
 * Navigation back from an execution to the object that produced it.
 *
 * A studio `ModelProject` is matched by `source_kind` FIRST — the universal async
 * solve tags studio runs with a looser `origin` ("visual_builder"), so routing by
 * origin alone would wrongly send them to the legacy builder. Everything else
 * routes by `origin` (the visual and AI builders both anchor on a builder document
 * but open at different views). Returns a locale-relative path (feed it to the
 * next-intl router/Link, which prepends the locale) or `null` when there is nothing
 * to navigate back to (e.g. a one-off import or an unknown origin).
 */
export function executionOriginHref(
  origin: string | undefined,
  sourceId: string | null | undefined,
  sourceKind?: ExecutionSourceKind | null
): string | null {
  if (!sourceId) return null;
  // Resolved through the same function the badge uses, so "what counts as a
  // studio run" is decided once. Writing the source_kind check out again here
  // would let the label and the link drift apart.
  switch (resolveOriginKey(origin, sourceKind)) {
    case "model_project":
      return `/studio/${sourceId}/build`;
    case "visual_builder":
      return `/builder/${sourceId}`;
    case "ai_builder":
      return `/builder/${sourceId}/chat`;
    case "template":
      return `/builder/templates/${sourceId}`;
    case "marketplace":
      // P1.5 fusion: a marketplace run executes a ModelProject. Historic rows
      // carry the legacy org-model id, which the backfill preserved as the
      // project id — so the studio route is valid for them too.
      return `/studio/${sourceId}/build`;
    default:
      return null;
  }
}
