import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { buildPageMetadata } from "@/lib/seo/metadata";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  return buildPageMetadata({ namespace: "metadata.privacy", path: "/privacy", locale });
}

export default async function PrivacyPage() {
  const t = await getTranslations("public");

  return (
    <div className="max-w-3xl mx-auto py-12 px-4">
      <h1 className="text-3xl font-bold mb-2">{t("privacy.title")}</h1>
      <p className="text-sm text-muted-foreground mb-8">{t("privacy.lastUpdated")}</p>

      <div className="space-y-8 text-muted-foreground leading-relaxed">
        <section>
          <h2 className="text-2xl font-semibold mt-8 mb-4 text-foreground">
            {t("privacy.section1.title")}
          </h2>
          <p>{t("privacy.section1.intro")}</p>
          <ul className="list-disc pl-6 mt-2 space-y-1">
            <li>{t.rich("privacy.section1.accountInfo", { strong: (chunks) => <strong>{chunks}</strong> })}</li>
            <li>{t.rich("privacy.section1.usageData", { strong: (chunks) => <strong>{chunks}</strong> })}</li>
            <li>{t.rich("privacy.section1.cookies", { strong: (chunks) => <strong>{chunks}</strong> })}</li>
            <li>{t.rich("privacy.section1.technicalData", { strong: (chunks) => <strong>{chunks}</strong> })}</li>
          </ul>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mt-8 mb-4 text-foreground">
            {t("privacy.section2.title")}
          </h2>
          <p>{t("privacy.section2.body")}</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mt-8 mb-4 text-foreground">
            {t("privacy.section3.title")}
          </h2>
          <p>{t("privacy.section3.intro")}</p>
          <ul className="list-disc pl-6 mt-2 space-y-1">
            <li>{t.rich("privacy.section3.stripe", { strong: (chunks) => <strong>{chunks}</strong> })}</li>
            <li>{t.rich("privacy.section3.discourse", { strong: (chunks) => <strong>{chunks}</strong> })}</li>
          </ul>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mt-8 mb-4 text-foreground">
            {t("privacy.section4.title")}
          </h2>
          <p>{t("privacy.section4.body")}</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mt-8 mb-4 text-foreground">
            {t("privacy.section5.title")}
          </h2>
          <p>{t("privacy.section5.intro")}</p>
          <ul className="list-disc pl-6 mt-2 space-y-1">
            <li>{t.rich("privacy.section5.access", { strong: (chunks) => <strong>{chunks}</strong> })}</li>
            <li>{t.rich("privacy.section5.erasure", { strong: (chunks) => <strong>{chunks}</strong> })}</li>
            <li>{t.rich("privacy.section5.portability", { strong: (chunks) => <strong>{chunks}</strong> })}</li>
            <li>{t.rich("privacy.section5.rectification", { strong: (chunks) => <strong>{chunks}</strong> })}</li>
            <li>{t.rich("privacy.section5.objection", { strong: (chunks) => <strong>{chunks}</strong> })}</li>
          </ul>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mt-8 mb-4 text-foreground">
            {t("privacy.section6.title")}
          </h2>
          <p>
            {t.rich("privacy.section6.body", {
              link: (chunks) => (
                <a href="mailto:support@jaot.io" className="underline hover:text-foreground">
                  {chunks}
                </a>
              ),
            })}
          </p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mt-8 mb-4 text-foreground">
            {t("privacy.section7.title")}
          </h2>
          <p>{t("privacy.section7.intro")}</p>
          <ul className="list-disc pl-6 mt-2 space-y-1">
            <li>{t.rich("privacy.section7.essential", { strong: (chunks) => <strong>{chunks}</strong> })}</li>
            <li>{t.rich("privacy.section7.analytics", { strong: (chunks) => <strong>{chunks}</strong> })}</li>
          </ul>
          <p className="mt-2">{t("privacy.section7.manage")}</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mt-8 mb-4 text-foreground">
            {t("privacy.section8.title")}
          </h2>
          <p>{t("privacy.section8.body")}</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mt-8 mb-4 text-foreground">
            {t("privacy.section9.title")}
          </h2>
          <p>
            {t.rich("privacy.section9.body", {
              link: (chunks) => (
                <a href="mailto:support@jaot.io" className="underline hover:text-foreground">
                  {chunks}
                </a>
              ),
            })}
          </p>
        </section>
      </div>
    </div>
  );
}
