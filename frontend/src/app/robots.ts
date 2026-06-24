import type { MetadataRoute } from "next";
import { BASE_URL } from "@/lib/seo/urls";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: [
          // REQ baseline (D-01) — private API + app surfaces
          // WR-06: blocks ALL of /api/* (FastAPI proxy — /api/v2/* and any future API
          // surface, including health/status routes). This is the correct posture for a
          // backend proxy. Public-facing status/marketing docs about the API live under a
          // DIFFERENT prefix (/docs/api/*) and are NOT affected by this rule.
          "/api/",
          "/admin/",
          "/builder/",
          "/solve/",
          "/triggers/",
          "/workspace/",
          "/billing/",
          // Real auth + org + maintenance pages (D-01 extensivo)
          // REQ DRIFT: SEO-02 lists /[locale]/auth/ as if an /auth/ route group existed
          // — it does NOT. Real auth pages are individual routes listed below, and their
          // locale-prefixed variants follow. Do NOT add /[locale]/auth/ here.
          "/login",
          "/signup",
          "/forgot-password",
          "/reset-password",
          "/verify-email",
          "/join/",
          "/org/",
          "/user/",
          "/maintenance",
          // Locale-prefixed variants — covers /es/login, /ca/signup, etc. (D-01)
          // Defense-in-depth: these routes are not in the sitemap, but are discoverable
          // via external backlinks (Stripe receipts, support emails, marketing collateral)
          // and should not be indexed. WR-02: enumerated against the real route tree under
          // src/app/[locale] — every non-public top-level segment now has both a bare and a
          // locale-prefixed disallow. (No /dashboard, /onboarding, /api-keys, /settings,
          // /notifications or /credits top-level routes exist — those surfaces are nested
          // under /workspace/ and /admin/, already covered by the prefix entries above.)
          "/*/admin/",
          "/*/builder/",
          "/*/solve/",
          "/*/triggers/",
          "/*/workspace/",
          "/*/billing/",
          "/*/login",
          "/*/signup",
          "/*/forgot-password",
          "/*/reset-password",
          "/*/verify-email",
          "/*/join/",
          "/*/org/",
          "/*/user/",
          "/*/maintenance",
        ],
      },
      // AI crawlers — explicitly allowed for GEO (generative-engine optimisation) visibility (D-03)
      // REQ-5 bots (GPTBot, ClaudeBot, Google-Extended, PerplexityBot, CCBot) plus 3 emergent:
      // OAI-SearchBot: feeds SearchGPT — distinct from GPTBot training corpus
      // AppleBot-Extended: Apple Intelligence / Spotlight — high-value premium-market signal
      // Meta-ExternalAgent: Llama training + Meta AI
      { userAgent: "GPTBot", allow: "/" },
      { userAgent: "ClaudeBot", allow: "/" },
      { userAgent: "Google-Extended", allow: "/" },
      { userAgent: "PerplexityBot", allow: "/" },
      { userAgent: "CCBot", allow: "/" },
      { userAgent: "OAI-SearchBot", allow: "/" },
      { userAgent: "AppleBot-Extended", allow: "/" },
      // Bytespider deliberately omitted — D-03 explicit skip (ByteDance reputational mismatch +
      // scraping-abuse signals incompatible with JAOT's posture). Do not add without revisiting D-03.
      { userAgent: "Meta-ExternalAgent", allow: "/" },
    ],
    sitemap: `${BASE_URL}/sitemap.xml`,
  };
}
