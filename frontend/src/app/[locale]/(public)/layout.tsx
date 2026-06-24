import Link from "next/link";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { LanguageSwitcher } from "@/components/i18n/LanguageSwitcher";
import { getTranslations, getLocale } from "next-intl/server";
import Footer from "@/components/layout/Footer";
import { PublicHeaderAuth } from "@/components/layout/PublicHeaderAuth";
import { HomeAnnouncementBanner } from "@/components/layout/HomeAnnouncementBanner";
import { PlausibleScript } from "@/components/analytics/PlausibleScript";
import { CwvReporter } from "@/components/analytics/CwvReporter";

export default async function PublicLayout({ children }: { children: React.ReactNode }) {
  const t = await getTranslations("public.nav");
  const locale = await getLocale();

  return (
    <>
      <HomeAnnouncementBanner locale={locale} />
      <header className="border-b border-border sticky top-0 z-40 bg-background/95 backdrop-blur">
        <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
          <Link href="/" className="text-xl font-serif text-primary">
            JAOT
          </Link>
          <div className="flex items-center gap-4">
            <nav className="hidden sm:flex items-center gap-4">
              <Link
                href="/marketplace"
                className="text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                {t("marketplace")}
              </Link>
              <Link
                href="/docs/getting-started/introduction"
                className="text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                {t("docs")}
              </Link>
              <Link
                href="/for-sellers"
                className="text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                {t("forSellers")}
              </Link>
            </nav>
            <LanguageSwitcher />
            <ThemeToggle />
            <PublicHeaderAuth />
          </div>
        </div>
      </header>
      <main id="main-content">{children}</main>
      <Footer />
      <PlausibleScript />
      <CwvReporter />
    </>
  );
}
