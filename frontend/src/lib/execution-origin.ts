/**
 * Navigation back from an execution to the object that produced it.
 *
 * Routes by `origin` (not `source_kind`) because the visual and AI builders
 * both anchor on a builder document but open at different views. Returns a
 * locale-relative path (feed it to the next-intl router/Link, which prepends
 * the locale) or `null` when there is nothing to navigate back to (e.g. a
 * one-off import or an unknown origin).
 */
export function executionOriginHref(
  origin: string | undefined,
  sourceId: string | null | undefined
): string | null {
  if (!sourceId) return null;
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
