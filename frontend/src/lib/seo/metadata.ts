import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { buildAlternates, localizedUrl, BASE_URL, type Locale } from "@/lib/seo/urls";

// D-08: og:locale mapping — OG format uses underscore, not BCP-47 hyphen.
// MUST be unconditional on every buildPageMetadata call (shallow-merge trap: if a page
// sets any openGraph key, Next.js REPLACES the parent layout's entire openGraph object,
// clobbering og:image and siteName set in layout.tsx).
const OG_LOCALE_MAP: Record<Locale, string> = {
  en: "en_US",
  es: "es_ES",
  ca: "ca_ES",
  fr: "fr_FR",
  de: "de_DE",
};

// D-01: Default brand OG/Twitter image. Resolved to https://jaot.io/og-default.png
// via metadataBase. Must be placed at frontend/public/og-default.png (1200x630).
const DEFAULT_OG_IMAGE = "/og-default.png";

interface BuildPageMetadataOptions {
  /** i18n namespace for static pages (e.g. "metadata.pricing"). Omit for dynamic pages. */
  namespace?: string;
  /** Route path, e.g. "/pricing". Used for canonical URL + alternates. */
  path: string;
  locale: string;
  /** Override title (for dynamic pages — bypasses namespace resolution). */
  title?: string;
  /** Override description (for dynamic pages — bypasses namespace resolution). */
  description?: string;
  /** Override OG image (page-specific; defaults to DEFAULT_OG_IMAGE). */
  image?: string;
}

/**
 * D-04: Extended buildPageMetadata — single source of truth for all public page metadata.
 *
 * Static pages: pass `namespace` (e.g. "metadata.pricing") and the helper resolves
 * t("title") / t("description") from messages/{locale}.json.
 *
 * Dynamic pages: pass data-derived `title` + `description` overrides — bypasses
 * getTranslations entirely.
 *
 * Always emits: metadataBase, title, description, alternates.canonical,
 * alternates.languages (5 locales + x-default), and a complete openGraph block
 * (title, description, url, type, siteName, locale, images) plus a twitter block
 * (card, title, description, images). The og:image is UNCONDITIONAL (D-07 / shallow-merge
 * trap: Next.js replaces the entire parent openGraph object — never rely on layout.tsx
 * to supply og:image for pages that set any openGraph key).
 */
export async function buildPageMetadata({
  namespace,
  path,
  locale,
  title: titleOverride,
  description: descriptionOverride,
  image,
}: BuildPageMetadataOptions): Promise<Metadata> {
  // Cast locale to Locale — callers are responsible for passing a valid locale.
  const canonicalUrl = localizedUrl(path, locale as Locale);
  const ogImage = image ?? DEFAULT_OG_IMAGE;
  const ogLocale = OG_LOCALE_MAP[locale as Locale] ?? "en_US";

  let resolvedTitle: string | undefined;
  let resolvedDescription: string | undefined;

  // Dispatch on `namespace`, NOT on "both overrides present". A dynamic caller may
  // legitimately supply only one of title/description (e.g. an MDX doc with a `title`
  // frontmatter key but no `description`). Branching on "both defined" would push such a
  // caller into the static branch, throw on the missing namespace, and drop the page's
  // canonical/alternates/openGraph entirely (CR-01). Static pages always pass a namespace;
  // dynamic pages never do.
  if (namespace) {
    // Static page path: resolve title/description from i18n namespace.
    // Key rename from scaffold: t("title") not t("meta.title").
    // Namespace is "metadata.{page}" so t("title") resolves metadata.{page}.title.
    const t = await getTranslations({ locale, namespace });
    resolvedTitle = t("title");
    resolvedDescription = t("description");
  } else if (titleOverride !== undefined || descriptionOverride !== undefined) {
    // Dynamic page path: caller provides data-derived title/description.
    // Either may be absent — a missing field stays undefined so Next.js inherits the
    // root-layout default rather than dropping it; canonical/alternates/openGraph are
    // still emitted below regardless.
    resolvedTitle = titleOverride;
    resolvedDescription = descriptionOverride;
  } else {
    // Neither a namespace (static) nor any override (dynamic) — a caller bug.
    throw new Error(
      "buildPageMetadata: pass `namespace` (static page) or a `title`/`description` override (dynamic page)",
    );
  }

  return {
    metadataBase: new URL(BASE_URL),
    title: resolvedTitle,
    description: resolvedDescription,
    alternates: {
      canonical: canonicalUrl,
      languages: buildAlternates(path),
    },
    // D-07: openGraph.title and openGraph.description MUST be set explicitly —
    // Next.js does NOT auto-copy top-level title/description into og:title/og:description.
    // D-01/D-07: openGraph.images is UNCONDITIONAL (no `...(image ? ... : {})` ternary)
    // to survive Next.js shallow-merge replacement of the parent openGraph object.
    openGraph: {
      title: resolvedTitle,
      description: resolvedDescription,
      url: canonicalUrl,
      type: "website",
      siteName: "JAOT",
      locale: ogLocale,
      images: [{ url: ogImage, width: 1200, height: 630, alt: "JAOT" }],
    },
    twitter: {
      card: "summary_large_image",
      title: resolvedTitle,
      description: resolvedDescription,
      images: [ogImage],
    },
  };
}
