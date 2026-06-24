/** Turn a docs URL slug segment into a human breadcrumb label.
 *  e.g. "getting-started" → "Getting Started".
 *
 *  Shared by the visible <DocsBreadcrumbs> client component and the
 *  server-rendered BreadcrumbList JSON-LD so the two never diverge
 *  (Phase 13.3 D-08 — single source of truth for breadcrumb labels).
 *  Pure, framework-free string transform: safe to import from both
 *  Server and Client Components. */
export function capitalizeSegment(segment: string): string {
  return segment.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
