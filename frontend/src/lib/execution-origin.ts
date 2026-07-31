/**
 * Where a solve came from: the origin slugs, how to label and colour them, and
 * how to navigate back to the object that produced one.
 *
 * The slug list mirrors `VALID_ORIGINS` in
 * `app/shared/constants/execution_provenance.py` — the backend sanitises unknown
 * values to "manual", so anything else in a row predates a slug or was written by
 * hand. `model_project` is not an origin: it is the `source_kind` the studio shows
 * in place of the looser origin the universal async solve tags its runs with.
 *
 * Every surface that renders an origin reads from here. Three of them used to
 * hardcode "manual vs triggered" instead, which is how the analytics legend ended
 * up printing "Automatic" three times in one chart — and calling studio runs
 * automatic when they are launched by hand.
 */

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
] as const;

export type OriginKey = (typeof ORIGIN_KEYS)[number];

/** Narrows a persisted slug to one this frontend knows how to label. */
export function isOriginKey(value: string | null | undefined): value is OriginKey {
  return value != null && (ORIGIN_KEYS as readonly string[]).includes(value);
}

/**
 * Resolves what a row should be shown as: the studio's `source_kind` wins over the
 * looser origin slug (same precedence as `executionOriginHref`). Returns `null` for
 * a slug this build does not know, so a distribution chart can keep it as its own
 * slice instead of silently folding it into "manual" and inflating that count.
 */
export function resolveOriginKey(
  origin: string | null | undefined,
  sourceKind?: string | null
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
};

/** Reserved for slugs `ORIGIN_KEYS` does not cover — paler than every real one. */
export const UNKNOWN_ORIGIN_COLOR = "#d1d5db";

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
  sourceKind?: string | null
): string | null {
  if (!sourceId) return null;
  if (sourceKind === "model_project") return `/studio/${sourceId}/build`;
  switch (origin) {
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
