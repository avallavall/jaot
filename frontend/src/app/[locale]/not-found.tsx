import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { Button } from "@/components/ui/button";

// Branded 404 for everything below the [locale] segment (audit F-03).
// Reached via notFound() calls (e.g. unknown marketplace models, F-04) and via
// the [...rest] catch-all route for URLs that match no page.
export default function NotFound() {
  const t = useTranslations("errors.notFound");

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-background text-foreground px-6 text-center">
      <Link href="/" className="text-xl font-serif text-primary mb-8">
        JAOT
      </Link>
      <p className="text-7xl font-serif text-primary mb-6" aria-hidden="true">
        404
      </p>
      <h1 className="text-2xl font-semibold mb-3">{t("title")}</h1>
      <p className="text-muted-foreground max-w-md mb-8">{t("message")}</p>
      <div className="flex flex-col sm:flex-row gap-4 justify-center">
        <Link href="/">
          <Button>{t("backHome")}</Button>
        </Link>
        <Link href="/marketplace">
          <Button variant="outline">{t("browseMarketplace")}</Button>
        </Link>
      </div>
    </div>
  );
}
