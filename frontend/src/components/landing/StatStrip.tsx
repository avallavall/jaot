import Link from "next/link";
import { ArrowUpRight, Github } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface StatItem {
  icon: LucideIcon;
  label: string;
}

interface StatStripProps {
  items: StatItem[];
  github: { label: string; href: string };
  className?: string;
}

/**
 * Honest credibility band under the hero: open-source / templates / marketplace /
 * MCP signals + a link to the public GitHub repo. No fake enterprise logos — the
 * proof points are real and reuse existing i18n keys.
 */
export function StatStrip({ items, github, className }: StatStripProps) {
  return (
    <div
      className={cn(
        "border-y border-border bg-muted/20",
        className,
      )}
    >
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-center gap-x-8 gap-y-3 px-6 py-5">
        {items.map((item) => (
          <span
            key={item.label}
            className="flex items-center gap-2 text-sm text-muted-foreground"
          >
            <item.icon className="h-4 w-4 text-accent" />
            {item.label}
          </span>
        ))}
        <Link
          href={github.href}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 text-sm font-medium text-foreground underline-offset-4 transition-colors hover:text-primary hover:underline"
        >
          <Github className="h-4 w-4" />
          {github.label}
          <ArrowUpRight className="h-3.5 w-3.5" />
        </Link>
      </div>
    </div>
  );
}
