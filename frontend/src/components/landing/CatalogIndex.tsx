import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { CATALOG_SUMMARY } from "./data/catalogSummary";

/**
 * The template catalogue as an index, counted from the YAML it ships from
 * (scripts/gen_landing_catalog.py).
 *
 * This replaced six hand-picked "use case" cards. A curated list drifts the
 * moment someone adds a template; the real catalogue is both larger and
 * self-maintaining, and the breadth is the argument — nobody expects an
 * optimization platform to cover aerospace and agriculture and payroll.
 *
 * Sector names are catalogue data, not interface copy, so they render as
 * authored rather than through next-intl — the same call made for MCP tool
 * names. Translating 34 sector labels into five locales would add a table that
 * silently goes stale every time a YAML file is added.
 *
 * Server Component: no client JavaScript.
 */
export async function CatalogIndex() {
  const t = await getTranslations("public.catalog");
  const { total, sectors, meta } = CATALOG_SUMMARY;

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-x-8 gap-y-3 border-b border-border pb-5">
        <p className="font-serif text-2xl text-foreground">
          {t("headline", { total, sectors: meta.sectorCount })}
        </p>
        <Link
          href="/marketplace"
          className="font-mono text-xs uppercase tracking-widest text-primary underline-offset-4 hover:underline"
        >
          {t("browse")}
        </Link>
      </div>

      {/* An index, not a card grid: dense, scannable, and the length is the point. */}
      <ul className="mt-8 grid gap-x-10 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
        {sectors.map((sector) => (
          <li key={sector.name} className="flex items-baseline gap-3">
            <span className="shrink-0 text-sm text-foreground">{sector.name}</span>
            <span
              className="h-px min-w-4 flex-1 translate-y-[-0.2em] border-b border-dotted border-border"
              aria-hidden
            />
            <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
              {sector.count}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
