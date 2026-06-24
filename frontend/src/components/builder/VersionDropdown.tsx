"use client";

import { useState, useCallback } from "react";
import { History, Bookmark } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuLabel,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { ModelVersionListItem } from "@/lib/types";
import { useTranslations } from "next-intl";

function formatRelativeTime(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diff = Math.floor((now - then) / 1000);

  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} hr ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)} day(s) ago`;
  return new Date(dateStr).toLocaleDateString();
}

interface VersionDropdownProps {
  documentId: string;
  saveCounter: number; // increments each time a save completes; triggers cache invalidation
  onViewAll: () => void;
  onRestore: (versionId: string) => void;
}

export function VersionDropdown({
  documentId,
  saveCounter,
  onViewAll,
  onRestore,
}: VersionDropdownProps) {
  const t = useTranslations("builder");
  const [versions, setVersions] = useState<ModelVersionListItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  // Track which saveCounter value the cached versions correspond to
  const [cachedAt, setCachedAt] = useState<number>(-1);

  const handleOpenChange = useCallback(
    async (open: boolean) => {
      if (!open) return;
      // Only refetch if cache is stale (saveCounter changed) or never loaded
      if (cachedAt === saveCounter && versions.length > 0) return;

      setIsLoading(true);
      try {
        const data = await api.listVersions(documentId, { limit: 5 });
        setVersions(data);
        setCachedAt(saveCounter);
      } catch {
        // Silently fail — versions are non-critical
      } finally {
        setIsLoading(false);
      }
    },
    [documentId, saveCounter, cachedAt, versions.length]
  );

  return (
    <DropdownMenu onOpenChange={handleOpenChange}>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="h-8 px-2 gap-1 text-xs">
          <History className="size-4" />
          {t("versions.history")}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-72">
        <DropdownMenuLabel className="text-xs text-muted-foreground font-normal">
          {t("versions.recentVersions")}
        </DropdownMenuLabel>

        {isLoading ? (
          <div className="px-2 py-3 text-xs text-muted-foreground text-center">
            {t("versions.loadingVersions")}
          </div>
        ) : versions.length === 0 ? (
          <div className="px-2 py-3 text-xs text-muted-foreground text-center">
            {t("versions.noVersions")}
          </div>
        ) : (
          versions.map((version) => (
            <DropdownMenuItem
              key={version.id}
              className="flex items-start gap-2 py-2 cursor-default"
              onSelect={(e) => e.preventDefault()}
            >
              {/* Bookmark icon for named versions, spacer otherwise */}
              <div className="mt-0.5 shrink-0 w-4">
                {version.is_named ? (
                  <Bookmark className="size-3.5 fill-current text-primary" />
                ) : null}
              </div>

              <div className="flex-1 min-w-0">
                <p
                  className={`text-xs truncate leading-tight ${
                    version.is_named ? "font-semibold" : "font-normal"
                  }`}
                >
                  {version.is_named && version.version_name
                    ? version.version_name
                    : version.change_summary}
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {formatRelativeTime(version.created_at)}
                  <span className="ml-1 opacity-60">#{version.sequence}</span>
                </p>
              </div>

              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-1.5 text-xs shrink-0 opacity-0 group-hover:opacity-100"
                onClick={(e) => {
                  e.stopPropagation();
                  onRestore(version.id);
                }}
              >
                {t("versions.restore")}
              </Button>
            </DropdownMenuItem>
          ))
        )}

        <DropdownMenuSeparator />

        <DropdownMenuItem
          onSelect={() => onViewAll()}
          className="text-xs text-muted-foreground cursor-pointer"
        >
          {t("versions.viewAll")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
