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
    heading: "forAuthors",
    links: [
      { href: "/docs/marketplace/publishing-models", key: "publishModel" },
      { href: "/marketplace", key: "browseModels" },
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

/**
 * The solvers this platform ships, and where each one lives.
 *
 * Mirrors the adapters in `app/domains/solver/adapters/`. Hexaly is not here:
 * it is profile-gated and not part of what a public instance runs. These are
 * licence-visible dependencies and the footer is where a stranger looks to see
 * what the site is built on — it used to name two of the four, while the SEO
 * description on the same pages already said all four.
 */
export const SOLVER_CREDITS = [
  { name: "SCIP", href: "https://www.scipopt.org/" },
  { name: "HiGHS", href: "https://highs.dev/" },
  { name: "CBC", href: "https://github.com/coin-or/Cbc" },
  { name: "GLPK", href: "https://www.gnu.org/software/glpk/" },
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
          <span data-testid="footer-solvers">
            {t("poweredBy")}{" "}
            {SOLVER_CREDITS.map(({ name, href }, index) => (
              <span key={name}>
                {index > 0 && (index === SOLVER_CREDITS.length - 1 ? " & " : ", ")}
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline hover:text-foreground transition-colors"
                >
                  {name}
                </a>
              </span>
            ))}
          </span>
          <span>&copy; {new Date().getFullYear()} {t("copyright")}</span>
        </div>
      </div>
    </footer>
  );
}
