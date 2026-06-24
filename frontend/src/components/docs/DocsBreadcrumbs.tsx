"use client";

import { Link, usePathname } from "@/i18n/navigation";
import { useTranslations } from "next-intl";
import { capitalizeSegment } from "@/lib/docs/breadcrumb-label";

export function DocsBreadcrumbs() {
  const pathname = usePathname();
  const t = useTranslations("common");

  const parts = pathname.split("/").filter(Boolean);
  const docsIndex = parts.indexOf("docs");
  if (docsIndex === -1) return null;

  const segments = parts.slice(docsIndex);

  return (
    <nav aria-label={t("breadcrumbsAriaLabel")} className="mb-4">
      <ol className="flex items-center gap-1.5 text-sm text-muted-foreground">
        {segments.map((segment, i) => {
          const isLast = i === segments.length - 1;
          const href = "/" + parts.slice(docsIndex, docsIndex + i + 1).join("/");

          return (
            <li key={segment} className="flex items-center gap-1.5">
              {i > 0 && (
                <span className="text-muted-foreground/50" aria-hidden="true">
                  /
                </span>
              )}
              {isLast ? (
                <span aria-current="page" className="text-foreground font-medium">
                  {capitalizeSegment(segment)}
                </span>
              ) : (
                <Link
                  href={href}
                  className="hover:text-foreground transition-colors"
                >
                  {capitalizeSegment(segment)}
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
