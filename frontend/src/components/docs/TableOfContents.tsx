"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { extractTocFromDOM, type TocItem } from "@/lib/docs/toc";
import { cn } from "@/lib/utils";

export function TableOfContents() {
  const t = useTranslations("common");
  const [items, setItems] = useState<TocItem[]>([]);
  const [activeId, setActiveId] = useState<string>("");

  useEffect(() => {
    // Wait for MDX content to render before extracting headings
    const timer = setTimeout(() => {
      setItems(extractTocFromDOM());
    }, 100);

    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (items.length === 0) return;

    const headingElements = items
      .map((item) => document.getElementById(item.id))
      .filter(Boolean) as HTMLElement[];

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveId(entry.target.id);
          }
        }
      },
      { rootMargin: "0px 0px -80% 0px" }
    );

    headingElements.forEach((el) => observer.observe(el));

    return () => observer.disconnect();
  }, [items]);

  if (items.length === 0) return null;

  return (
    <nav
      className="w-56 shrink-0 hidden xl:block py-6 px-4 sticky top-14"
      aria-label={t("tableOfContentsAriaLabel")}
    >
      <p className="text-sm font-semibold text-foreground mb-3">{t("onThisPage")}</p>
      <ul className="space-y-1">
        {items.map((item) => (
          <li key={item.id}>
            <a
              href={`#${item.id}`}
              className={cn(
                "block text-sm py-0.5 transition-colors",
                item.level === 3 && "pl-4",
                activeId === item.id
                  ? "text-primary font-medium"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {item.text}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
