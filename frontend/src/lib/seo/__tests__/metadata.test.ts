import { describe, it, expect, vi } from "vitest";
import { buildPageMetadata } from "@/lib/seo/metadata";

// Mock next-intl getTranslations to return a simple key-based translator
vi.mock("next-intl/server", () => ({
  getTranslations: vi.fn().mockResolvedValue((key: string) => `test-${key}`),
}));

describe("buildPageMetadata", () => {
  it("returns localized title and description for a static page", async () => {
    const result = await buildPageMetadata({
      namespace: "metadata.pricing",
      path: "/pricing",
      locale: "es",
    });

    // Top-level title and description
    expect(result.title).toBe("test-title");
    expect(result.description).toBe("test-description");

    // og:title must be explicit — Next.js does NOT copy title → og:title
    const og = result.openGraph as Record<string, unknown>;
    expect(og?.title).toBe("test-title");
    expect(og?.description).toBe("test-description");

    // D-08: og:locale for "es" → "es_ES"
    expect(og?.locale).toBe("es_ES");

    // og:type and og:siteName
    expect(og?.type).toBe("website");
    expect(og?.siteName).toBe("JAOT");

    // D-01: og:image must always be present (not conditional)
    expect(og?.images).toBeDefined();
    expect(Array.isArray(og?.images)).toBe(true);

    // Twitter card — cast required: Next.js Twitter type is a wide union, use double cast
    const tw = result.twitter as unknown as Record<string, unknown>;
    expect(tw?.card).toBe("summary_large_image");
    expect(tw?.title).toBe("test-title");
    expect(tw?.description).toBe("test-description");
    expect(tw?.images).toBeDefined();
  });

  it("uses title/description overrides for dynamic pages without calling getTranslations", async () => {
    const { getTranslations } = await import("next-intl/server");
    vi.clearAllMocks();

    const result = await buildPageMetadata({
      path: "/marketplace/some-model",
      locale: "fr",
      title: "My Model — JAOT",
      description: "A model description",
    });

    // Overrides passed through correctly
    expect(result.title).toBe("My Model — JAOT");
    expect(result.description).toBe("A model description");

    // D-08: og:locale for "fr" → "fr_FR"
    const og = result.openGraph as Record<string, unknown>;
    expect(og?.locale).toBe("fr_FR");

    // og:title/description use overrides
    expect(og?.title).toBe("My Model — JAOT");
    expect(og?.description).toBe("A model description");

    // Dynamic path: getTranslations must NOT have been called
    expect(getTranslations).not.toHaveBeenCalled();
  });

  it("maps de locale to de_DE", async () => {
    const result = await buildPageMetadata({
      namespace: "metadata.home",
      path: "",
      locale: "de",
    });
    const og = result.openGraph as Record<string, unknown>;
    expect(og?.locale).toBe("de_DE");
  });

  it("home root (path '') emits all 6 alternates with no trailing slash", async () => {
    // Regression: the home page used to pass path: "/" instead of "" (the root
    // convention encoded by buildAlternates/localizedUrl and layout.tsx). "/" makes
    // localizedUrl emit trailing-slash URLs that diverge from the layout's slash-less
    // canonical/hreflang and break seo-canonical-hreflang.spec.ts for the home route.
    const result = await buildPageMetadata({
      namespace: "metadata.home",
      path: "",
      locale: "en",
    });

    // canonical for the English root is the bare base URL — no trailing slash.
    expect(result.alternates?.canonical).toBe("https://jaot.io");

    const langs = result.alternates?.languages as Record<string, string>;
    // Exactly 6 entries: en, es, ca, fr, de, x-default.
    expect(Object.keys(langs)).toHaveLength(6);
    // Root URLs carry no trailing slash and match buildAlternates("") in layout.tsx.
    expect(langs["en"]).toBe("https://jaot.io");
    expect(langs["x-default"]).toBe("https://jaot.io");
    expect(langs["es"]).toBe("https://jaot.io/es");
    expect(langs["ca"]).toBe("https://jaot.io/ca");
    expect(langs["fr"]).toBe("https://jaot.io/fr");
    expect(langs["de"]).toBe("https://jaot.io/de");
  });

  it("maps en locale to en_US", async () => {
    const result = await buildPageMetadata({
      namespace: "metadata.pricing",
      path: "/pricing",
      locale: "en",
    });
    const og = result.openGraph as Record<string, unknown>;
    expect(og?.locale).toBe("en_US");
  });

  it("maps ca locale to ca_ES", async () => {
    const result = await buildPageMetadata({
      namespace: "metadata.terms",
      path: "/terms",
      locale: "ca",
    });
    const og = result.openGraph as Record<string, unknown>;
    expect(og?.locale).toBe("ca_ES");
  });

  it("image override flows to openGraph.images and twitter.images", async () => {
    const result = await buildPageMetadata({
      namespace: "metadata.pricing",
      path: "/pricing",
      locale: "en",
      image: "/custom-og.png",
    });
    const og = result.openGraph as Record<string, unknown>;
    const images = og?.images as Array<Record<string, unknown>>;
    expect(images[0]?.url).toBe("/custom-og.png");
    const twitterImages = result.twitter?.images as string[];
    expect(twitterImages[0]).toBe("/custom-og.png");
  });

  it("defaults to brand PNG when no image override provided", async () => {
    const result = await buildPageMetadata({
      namespace: "metadata.pricing",
      path: "/pricing",
      locale: "en",
    });
    const og = result.openGraph as Record<string, unknown>;
    const images = og?.images as Array<Record<string, unknown>>;
    expect(images[0]?.url).toBe("/og-default.png");
    const twitterImages = result.twitter?.images as string[];
    expect(twitterImages[0]).toBe("/og-default.png");
  });

  it("throws when neither namespace nor any override is provided", async () => {
    await expect(
      buildPageMetadata({
        path: "/pricing",
        locale: "en",
        // no namespace, no title/description overrides
      }),
    ).rejects.toThrow("buildPageMetadata: pass `namespace`");
  });

  it("CR-01: dynamic page with only a title (no description) still emits canonical + og, no throw", async () => {
    const { getTranslations } = await import("next-intl/server");
    vi.clearAllMocks();

    // Mirrors docs/[...slug] when an MDX file has a `title` frontmatter key but no
    // `description`. Must NOT fall into the static branch and throw (which would drop
    // canonical/alternates/og entirely via the caller's catch → {}).
    const result = await buildPageMetadata({
      path: "/docs/getting-started",
      locale: "es",
      title: "Getting Started",
      // description intentionally omitted
    });

    expect(result.title).toBe("Getting Started");
    expect(result.description).toBeUndefined(); // inherits root-layout default
    // canonical + alternates still present — the regression this guards against
    expect(result.alternates?.canonical as string).toContain("/es/docs/getting-started");
    const langs = result.alternates?.languages as Record<string, string>;
    expect(langs).toHaveProperty("x-default");
    const og = result.openGraph as Record<string, unknown>;
    expect(og?.title).toBe("Getting Started");
    expect(og?.locale).toBe("es_ES");
    expect(og?.images).toBeDefined();
    // Dynamic path: no namespace → getTranslations must NOT be called
    expect(getTranslations).not.toHaveBeenCalled();
  });

  it("sets metadataBase and correct canonical URL", async () => {
    const result = await buildPageMetadata({
      namespace: "metadata.pricing",
      path: "/pricing",
      locale: "es",
    });
    expect(result.metadataBase).toBeDefined();
    // canonical for es locale uses /{locale}{path} prefix
    const canonical = result.alternates?.canonical as string;
    expect(canonical).toContain("/es/pricing");
    // alternates.languages includes all 5 locales + x-default
    const langs = result.alternates?.languages as Record<string, string>;
    expect(langs).toHaveProperty("en");
    expect(langs).toHaveProperty("es");
    expect(langs).toHaveProperty("ca");
    expect(langs).toHaveProperty("fr");
    expect(langs).toHaveProperty("de");
    expect(langs).toHaveProperty("x-default");
  });
});
