import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { buildPageMetadata } from "@/lib/seo/metadata";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  return buildPageMetadata({
    namespace: "metadata.terms",
    path: "/terms",
    locale,
  });
}

export default async function TermsPage() {
  const t = await getTranslations("public");

  return (
    <div className="max-w-3xl mx-auto py-12 px-4">
      <h1 className="text-3xl font-bold mb-2">{t("terms.title")}</h1>
      <p className="text-sm text-muted-foreground mb-8">
        {t("terms.lastUpdated")}
      </p>

      <div className="space-y-8 text-muted-foreground leading-relaxed">
        <section>
          <h2 className="text-2xl font-semibold mt-8 mb-4 text-foreground">
            {t("terms.section1.title")}
          </h2>
          <p>{t("terms.section1.body")}</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mt-8 mb-4 text-foreground">
            {t("terms.section2.title")}
          </h2>
          <p>{t("terms.section2.body")}</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mt-8 mb-4 text-foreground">
            {t("terms.section3.title")}
          </h2>
          <p>{t("terms.section3.intro")}</p>
          <ul className="list-disc pl-6 mt-2 space-y-1">
            <li>{t("terms.section3.item1")}</li>
            <li>{t("terms.section3.item2")}</li>
            <li>{t("terms.section3.item3")}</li>
            <li>{t("terms.section3.item4")}</li>
            <li>{t("terms.section3.item5")}</li>
          </ul>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mt-8 mb-4 text-foreground">
            {t("terms.section4.title")}
          </h2>
          <p>{t("terms.section4.body1")}</p>
          <p className="mt-2">{t("terms.section4.body2")}</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mt-8 mb-4 text-foreground">
            {t("terms.section5.title")}
          </h2>
          <p>{t("terms.section5.body1")}</p>
          <p className="mt-2">{t("terms.section5.body2")}</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mt-8 mb-4 text-foreground">
            {t("terms.section6.title")}
          </h2>
          <p>{t("terms.section6.body1")}</p>
          <p className="mt-2">{t("terms.section6.body2")}</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mt-8 mb-4 text-foreground">
            {t("terms.section7.title")}
          </h2>
          <p>{t("terms.section7.body")}</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mt-8 mb-4 text-foreground">
            {t("terms.section8.title")}
          </h2>
          <p>{t("terms.section8.body")}</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mt-8 mb-4 text-foreground">
            {t("terms.section9.title")}
          </h2>
          <p>{t("terms.section9.body")}</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mt-8 mb-4 text-foreground">
            {t("terms.section10.title")}
          </h2>
          <p>{t("terms.section10.body")}</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mt-8 mb-4 text-foreground">
            {t("terms.section11.title")}
          </h2>
          <p>{t("terms.section11.body")}</p>
        </section>

        <section>
          <h2 className="text-2xl font-semibold mt-8 mb-4 text-foreground">
            {t("terms.section12.title")}
          </h2>
          <p>
            {t.rich("terms.section12.body", {
              link: (chunks) => (
                <a
                  href="mailto:support@jaot.io"
                  className="underline hover:text-foreground"
                >
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
