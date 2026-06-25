import type { Metadata } from "next";
import { Fraunces } from "next/font/google";
import { NextIntlClientProvider, hasLocale } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import { Toaster } from "sonner";
import "../globals.css";

// Brand display serif. Fraunces is an "old-style" serif with optical sizing and
// soft/wonky character — it carries the vintage/editorial identity that the bare
// `font-serif` (browser-default Georgia/Times) never could. Exposed as the
// --font-fraunces CSS variable and wired to Tailwind's `font-serif` via the
// --font-serif token in globals.css, so every existing `font-serif` call site
// (logo, headings across the app) upgrades automatically.
const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--font-fraunces",
  display: "swap",
  axes: ["opsz"],
});
import { routing } from "@/i18n/routing";
import { buildAlternates, localizedUrl, BASE_URL, type Locale } from "@/lib/seo/urls";
import { Providers } from "./providers";
import { CookieConsent } from "@/components/legal/CookieConsent";
import { FallbackProvider } from "@/components/i18n/FallbackProvider";
import { SkipLink } from "@/components/layout/SkipLink";

type Props = {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
};

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;

  // Build alternates for all 5 locales + x-default via unified helper (SC3)
  const languages = buildAlternates("");

  const t = await getTranslations({ locale, namespace: "common" });

  return {
    metadataBase: new URL(BASE_URL),
    title: `${t("jaot")} - ${t("optimizationAsAService")}`,
    description: t("siteDescription"),
    alternates: {
      canonical: localizedUrl("", locale as Locale),
      languages,
    },
    // D-06: social defaults — shallow-merge means these only apply to pages that
    // emit NO openGraph key of their own. All pages migrated to buildPageMetadata
    // carry their own openGraph. These are kept as last-resort fallback only.
    openGraph: {
      siteName: "JAOT",
      type: "website",
      images: [{ url: "/og-default.png", width: 1200, height: 630, alt: "JAOT" }],
    },
    twitter: {
      card: "summary_large_image",
      images: ["/og-default.png"],
    },
  };
}

export default async function LocaleLayout({ children, params }: Props) {
  const { locale } = await params;

  if (!hasLocale(routing.locales, locale)) {
    notFound();
  }

  setRequestLocale(locale);

  return (
    <html lang={locale} className={fraunces.variable} suppressHydrationWarning>
      <body className="font-sans antialiased">
        <SkipLink />
        <NextIntlClientProvider>
          <FallbackProvider>
            <Providers>{children}</Providers>
            <CookieConsent />
          </FallbackProvider>
        </NextIntlClientProvider>
        <Toaster richColors position="bottom-right" />
      </body>
    </html>
  );
}
