"use client";

import Link from "next/link";
import { ChevronRight, Home } from "lucide-react";
import { useTranslations } from "next-intl";
import { useAuth } from "@/contexts/AuthContext";

interface WorkspaceBreadcrumbProps {
  section: string;
  sectionHref: string;
  itemName?: string;
}

export function WorkspaceBreadcrumb({
  section,
  sectionHref,
  itemName,
}: WorkspaceBreadcrumbProps) {
  const { activeWorkspaceId, activeWorkspaceName } = useAuth();
  const t = useTranslations("common");

  return (
    <nav className="flex items-center gap-1.5 text-sm text-muted-foreground mb-4">
      <Link href="/" className="hover:text-foreground transition-colors" aria-label={t("breadcrumbs.home")}>
        <Home className="h-4 w-4" />
      </Link>

      {activeWorkspaceId && (
        <>
          <ChevronRight className="h-3.5 w-3.5" />
          <Link
            href={`/workspace/workspaces/${activeWorkspaceId}`}
            className="hover:text-foreground transition-colors"
          >
            {activeWorkspaceName ?? t("breadcrumbs.workspace")}
          </Link>
        </>
      )}

      <ChevronRight className="h-3.5 w-3.5" />
      <Link href={sectionHref} className="hover:text-foreground transition-colors">
        {section}
      </Link>

      {itemName && (
        <>
          <ChevronRight className="h-3.5 w-3.5" />
          <span className="text-foreground font-medium truncate max-w-[200px]">
            {itemName}
          </span>
        </>
      )}
    </nav>
  );
}
