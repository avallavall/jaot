"use client";

import { useState, useEffect } from "react";
import { Link, usePathname } from "@/i18n/navigation";
import { ChevronDown, ChevronRight } from "lucide-react";
import { docsNavigation, type DocsNavItem } from "@/lib/docs/navigation";
import { cn } from "@/lib/utils";

function findActiveSection(items: DocsNavItem[], pathname: string): string | null {
  for (const item of items) {
    if (item.children) {
      for (const child of item.children) {
        if (child.slug && pathname.includes(`/docs/${child.slug}`)) {
          return item.title;
        }
      }
    }
  }
  return null;
}

interface DocsSidebarProps {
  onNavigate?: () => void;
}

export function DocsSidebar({ onNavigate }: DocsSidebarProps) {
  const pathname = usePathname();
  const activeSection = findActiveSection(docsNavigation, pathname);

  const [expanded, setExpanded] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {};
    for (const item of docsNavigation) {
      initial[item.title] = item.title === activeSection;
    }
    return initial;
  });

  useEffect(() => {
    if (activeSection) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setExpanded((prev) => ({ ...prev, [activeSection]: true }));
    }
  }, [activeSection]);

  const toggleSection = (title: string) => {
    setExpanded((prev) => ({ ...prev, [title]: !prev[title] }));
  };

  return (
    <nav className="w-64 shrink-0 border-r border-border overflow-y-auto py-6 px-4" aria-label="Documentation sidebar">
      <ul className="space-y-1">
        {docsNavigation.map((section) => (
          <li key={section.title}>
            <button
              onClick={() => toggleSection(section.title)}
              className="flex items-center justify-between w-full px-2 py-1.5 text-sm font-semibold text-foreground hover:bg-muted/50 rounded-md transition-colors"
              aria-expanded={expanded[section.title]}
            >
              {section.title}
              {expanded[section.title] ? (
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              )}
            </button>
            {expanded[section.title] && section.children && (
              <ul className="mt-1 ml-2 space-y-0.5">
                {section.children.map((child) => {
                  const isActive = child.slug && pathname.includes(`/docs/${child.slug}`);
                  return (
                    <li key={child.slug ?? child.title}>
                      {child.slug ? (
                        <Link
                          href={`/docs/${child.slug}`}
                          onClick={onNavigate}
                          className={cn(
                            "block px-2 py-1.5 text-sm rounded-md transition-colors",
                            isActive
                              ? "text-primary font-bold bg-primary/5"
                              : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
                          )}
                        >
                          {child.title}
                        </Link>
                      ) : (
                        <span className="block px-2 pt-4 pb-1 text-xs font-semibold uppercase tracking-wider text-foreground/70">
                          {child.title}
                        </span>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </nav>
  );
}
