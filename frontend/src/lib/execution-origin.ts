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
      return `/solve/${sourceId}`;
    default:
      return null;
  }
}
