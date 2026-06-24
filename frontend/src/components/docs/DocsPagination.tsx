"use client";

import { Link, usePathname } from "@/i18n/navigation";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { getPrevNext } from "@/lib/docs/navigation";

export function DocsPagination() {
  const pathname = usePathname();

  const parts = pathname.split("/").filter(Boolean);
  const docsIndex = parts.indexOf("docs");
  if (docsIndex === -1) return null;

  const currentSlug = parts.slice(docsIndex + 1).join("/");
  const { prev, next } = getPrevNext(currentSlug);

  if (!prev && !next) return null;

  return (
    <nav className="flex justify-between items-center mt-12 pt-6 border-t border-border" aria-label="Pagination">
      {prev ? (
        <Link
          href={`/docs/${prev.slug}`}
          className="group flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          <div>
            <div className="text-sm text-muted-foreground">Previous</div>
            <div className="font-medium text-foreground group-hover:text-primary transition-colors">
              {prev.title}
            </div>
          </div>
        </Link>
      ) : (
        <div />
      )}

      {next ? (
        <Link
          href={`/docs/${next.slug}`}
          className="group flex items-center gap-2 text-right text-muted-foreground hover:text-foreground transition-colors"
        >
          <div>
            <div className="text-sm text-muted-foreground">Next</div>
            <div className="font-medium text-foreground group-hover:text-primary transition-colors">
              {next.title}
            </div>
          </div>
          <ArrowRight className="h-4 w-4" />
        </Link>
      ) : (
        <div />
      )}
    </nav>
  );
}
