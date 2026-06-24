import type { Metadata } from "next";
import type { WebPage, WithContext } from "schema-dts";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { Button } from "@/components/ui/button";
import { buildPageMetadata } from "@/lib/seo/metadata";
import { JsonLd } from "@/components/seo/JsonLd";
import { BASE_URL } from "@/lib/seo/urls";
import { ArrowRight } from "lucide-react";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  return buildPageMetadata({ namespace: "metadata.sellers", path: "/for-sellers", locale });
}

export default async function ForSellersPage() {
  const [t, tm] = await Promise.all([
    getTranslations("public"),
    getTranslations("metadata.sellers"),
  ]);

  const jsonLd: WithContext<WebPage> = {
    "@context": "https://schema.org",
    "@type": "WebPage",
    name: tm("title"),
    description: tm("description"),
    url: `${BASE_URL}/for-sellers`,
    provider: {
      "@type": "Organization",
      name: "JAOT",
      url: BASE_URL,
    } as WithContext<WebPage>["provider"],
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      <JsonLd data={jsonLd} />

      {/* Section 1: Hero */}
      <section className="py-24 text-center max-w-6xl mx-auto px-6">
        <h1 className="text-4xl md:text-5xl font-serif mb-6">
          {t("sellers.hero.title")}
        </h1>
        <p className="text-lg text-muted-foreground max-w-2xl mx-auto mb-10">
          {t("sellers.hero.subtitle")}
        </p>
        <div className="flex flex-col sm:flex-row gap-4 justify-center">
          <Link href="/signup">
            <Button size="lg" className="gap-2 px-10">
              {t("sellers.hero.cta")}
              <ArrowRight className="w-4 h-4" />
            </Button>
          </Link>
          <Link href="/marketplace">
            <Button variant="outline" size="lg">
              {t("sellers.hero.secondaryCta")}
            </Button>
          </Link>
        </div>
      </section>

      {/* Section 2: Stats / Social Proof */}
      <section className="bg-muted/30 border-y border-border py-16">
        <div className="max-w-6xl mx-auto px-6 grid grid-cols-1 md:grid-cols-3 gap-8 text-center">
          <div>
            <p className="text-4xl font-serif text-primary mb-2">
              {t("sellers.stats.revenueShare")}
            </p>
            <p className="text-muted-foreground">
              {t("sellers.stats.revenueShareDesc")}
            </p>
          </div>
          <div>
            <p className="text-4xl font-serif text-primary mb-2">
              {t("sellers.stats.globalReach")}
            </p>
            <p className="text-muted-foreground">
              {t("sellers.stats.globalReachDesc")}
            </p>
          </div>
          <div>
            <p className="text-4xl font-serif text-primary mb-2">
              {t("sellers.stats.simplePayouts")}
            </p>
            <p className="text-muted-foreground">
              {t("sellers.stats.simplePayoutsDesc")}
            </p>
          </div>
        </div>
      </section>

      {/* Section 3: How It Works */}
      <section className="py-24">
        <div className="max-w-6xl mx-auto px-6">
          <h2 className="text-3xl font-serif mb-16 text-center">
            {t("sellers.howItWorks.title")}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-12">
            {(["step1", "step2", "step3"] as const).map((step, i) => (
              <div key={step} className="text-center">
                <div className="w-12 h-12 rounded-full bg-primary text-primary-foreground flex items-center justify-center text-lg font-bold mx-auto mb-6">
                  {i + 1}
                </div>
                <h3 className="text-xl font-semibold mb-3">
                  {t(`sellers.howItWorks.${step}.title`)}
                </h3>
                <p className="text-muted-foreground">
                  {t(`sellers.howItWorks.${step}.description`)}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Section 4: Why JAOT */}
      <section className="bg-muted/30 border-y border-border py-24">
        <div className="max-w-6xl mx-auto px-6">
          <h2 className="text-3xl font-serif mb-12 text-center">
            {t("sellers.whyJAOT.title")}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            {(
              [
                "firstMarketplace",
                "lowCommission",
                "professionalSolver",
                "aiDistribution",
              ] as const
            ).map((key) => (
              <div
                key={key}
                className="bg-card border border-border rounded-lg p-8"
              >
                <h3 className="text-xl font-semibold mb-3">
                  {t(`sellers.whyJAOT.${key}.title`)}
                </h3>
                <p className="text-muted-foreground">
                  {t(`sellers.whyJAOT.${key}.description`)}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Section 5: Revenue Transparency */}
      <section className="py-24">
        <div className="max-w-6xl mx-auto px-6">
          <h2 className="text-3xl font-serif mb-12 text-center">
            {t("sellers.revenue.title")}
          </h2>
          <div className="bg-card border border-border rounded-lg p-8 max-w-2xl mx-auto">
            <div className="space-y-6">
              <div className="flex items-center gap-4">
                <div className="w-8 h-8 rounded-full bg-primary/10 text-primary flex items-center justify-center text-sm font-bold shrink-0">
                  1
                </div>
                <p className="text-foreground font-medium">
                  {t("sellers.revenue.youSetPrice")}
                </p>
              </div>
              <div className="flex items-center gap-4">
                <div className="w-8 h-8 rounded-full bg-primary/10 text-primary flex items-center justify-center text-sm font-bold shrink-0">
                  2
                </div>
                <p className="text-foreground font-medium">
                  {t("sellers.revenue.customerActivates")}
                </p>
              </div>
              <div className="flex items-center gap-4">
                <div className="w-8 h-8 rounded-full bg-primary/10 text-primary flex items-center justify-center text-sm font-bold shrink-0">
                  3
                </div>
                <p className="text-foreground font-medium">
                  {t("sellers.revenue.platformCommission")}
                </p>
              </div>
              <div className="flex items-center gap-4">
                <div className="w-8 h-8 rounded-full bg-primary/10 text-primary flex items-center justify-center text-sm font-bold shrink-0">
                  4
                </div>
                <p className="text-foreground font-medium">
                  {t("sellers.revenue.youReceive")}
                </p>
              </div>
              <div className="border-t border-border pt-6 mt-6">
                <p className="text-sm text-muted-foreground text-center">
                  {t("sellers.revenue.example")}
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Section 6: Final CTA */}
      <section className="bg-muted/30 border-y border-border py-24 text-center">
        <div className="max-w-6xl mx-auto px-6">
          <h2 className="text-3xl font-serif mb-4">{t("sellers.cta.title")}</h2>
          <p className="text-muted-foreground mb-8 max-w-md mx-auto">
            {t("sellers.cta.subtitle")}
          </p>
          <Link href="/signup">
            <Button size="lg" className="gap-2 px-10">
              {t("sellers.cta.button")}
              <ArrowRight className="w-4 h-4" />
            </Button>
          </Link>
        </div>
      </section>
    </div>
  );
}
