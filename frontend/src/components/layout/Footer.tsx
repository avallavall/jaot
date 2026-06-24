import Link from "next/link";
import { getTranslations } from "next-intl/server";

// Footer link columns — heading + links live together so adding or reordering a
// link is a data edit, not structural JSX surgery across four near-identical blocks.
const FOOTER_COLUMNS = [
  {
    heading: "product",
    links: [
      { href: "/signup", key: "aiBuilder" },
      { href: "/marketplace", key: "marketplace" },
      { href: "/llms.txt", key: "mcpIntegration" },
    ],
  },
  {
    heading: "forSellers",
    links: [
      { href: "/for-sellers", key: "howItWorks" },
      { href: "/docs/marketplace/publishing-models", key: "publishModel" },
    ],
  },
  {
    heading: "developers",
    links: [
      { href: "/docs/getting-started/introduction", key: "docs" },
      { href: "/docs/api/solve", key: "apiReference" },
      { href: "/docs/mcp/overview", key: "mcpEndpoint" },
    ],
  },
  {
    heading: "legal",
    links: [
      { href: "/contact", key: "contact" },
      { href: "/terms", key: "terms" },
      { href: "/privacy", key: "privacy" },
      { href: "/licenses", key: "licenses" },
    ],
  },
] as const;

export default async function Footer() {
  const t = await getTranslations("public.footer");

  return (
    <footer className="border-t border-border py-10">
      <div className="max-w-6xl mx-auto px-6">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
          {FOOTER_COLUMNS.map((column) => (
            <div key={column.heading}>
              <p className="text-sm font-medium mb-3">{t(column.heading)}</p>
              <div className="flex flex-col gap-2 text-sm text-muted-foreground">
                {column.links.map((link) => (
                  <Link
                    key={link.href}
                    href={link.href}
                    className="hover:text-foreground transition-colors"
                  >
                    {t(link.key)}
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="mt-8 pt-6 border-t border-border flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-muted-foreground">
          <span className="text-lg font-serif text-primary">JAOT</span>
          <span>&copy; {new Date().getFullYear()} {t("copyright")}</span>
        </div>
      </div>
    </footer>
  );
}
