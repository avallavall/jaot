import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { ContactForm } from "@/components/contact/ContactForm";
import { buildPageMetadata } from "@/lib/seo/metadata";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  return buildPageMetadata({ namespace: "metadata.contact", path: "/contact", locale });
}

export default async function ContactPage() {
  const t = await getTranslations("contact");

  return (
    <div className="max-w-2xl mx-auto py-12 px-4">
      <h1 className="text-3xl font-bold mb-2">{t("title")}</h1>
      <p className="text-muted-foreground mb-8">{t("subtitle")}</p>
      <ContactForm />
    </div>
  );
}
