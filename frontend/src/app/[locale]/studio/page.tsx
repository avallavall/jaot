"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Trash2 } from "lucide-react";
import { Link, useRouter } from "@/i18n/navigation";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import type { ProjectListItem } from "@/lib/types";

function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString();
}

/**
 * Studio home — the real "My Models" list. Fetches the org's ModelProjects and
 * links each into its workspace. Loading skeleton, empty state (only on a 0-length
 * fetch), and an error state with retry.
 */
export default function StudioHomePage() {
  const t = useTranslations("studio");
  const router = useRouter();
  const { activeWorkspaceId } = useAuth();
  const [projects, setProjects] = useState<ProjectListItem[] | null>(null);
  const [error, setError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  // State is only set from async callbacks here (never synchronously) so this
  // doesn't trip react-hooks/set-state-in-effect.
  useEffect(() => {
    let active = true;
    api
      .listProjects({ status: "active" }, activeWorkspaceId ?? undefined)
      .then((p) => {
        if (active) {
          setProjects(p);
          setError(false);
        }
      })
      .catch(() => {
        if (active) setError(true);
      });
    return () => {
      active = false;
    };
  }, [activeWorkspaceId, reloadKey]);

  // Retry is a user event (setState here is fine): reset to the loading state and
  // bump the key so the effect refetches.
  const retry = () => {
    setProjects(null);
    setError(false);
    setReloadKey((k) => k + 1);
  };

  const ws = activeWorkspaceId ?? undefined;

  // Archive (soft-delete) a model: optimistically drop it from the list, then
  // offer an Undo that restores it (status -> active). Reverts the row on failure.
  const archive = async (p: ProjectListItem) => {
    setProjects((prev) => prev?.filter((x) => x.id !== p.id) ?? prev);
    try {
      await api.archiveProject(p.id, ws);
      toast.success(t("modelArchived", { name: p.name || t("untitled") }), {
        action: {
          label: t("undo"),
          onClick: () => {
            api
              .updateProject(p.id, { status: "active" }, ws)
              .then(() => setProjects((prev) => (prev ? [p, ...prev] : prev)))
              .catch(() => toast.error(t("archiveError")));
          },
        },
      });
    } catch {
      setProjects((prev) => (prev ? [p, ...prev] : prev));
      toast.error(t("archiveError"));
    }
  };

  return (
    <div className="max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">{t("myModels")}</h1>
          <p className="text-muted-foreground text-sm mt-1">{t("myModelsSubtitle")}</p>
        </div>
        <Button onClick={() => router.push("/studio/new")}>{t("newModel")}</Button>
      </div>

      {error ? (
        <div className="rounded-lg border border-dashed p-10 text-center text-sm">
          <p className="text-muted-foreground">{t("myModelsError")}</p>
          <Button variant="outline" size="sm" className="mt-3" onClick={retry}>
            {t("retry")}
          </Button>
        </div>
      ) : projects === null ? (
        <div className="space-y-2" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-16 rounded-lg border bg-muted/30 animate-pulse" />
          ))}
        </div>
      ) : projects.length === 0 ? (
        <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">
          {t("myModelsEmpty")}
        </div>
      ) : (
        <ul className="space-y-2">
          {projects.map((p) => (
            <li
              key={p.id}
              className="flex items-center gap-2 rounded-lg border p-4 hover:border-primary/50 hover:shadow-sm transition-all"
            >
              <Link
                href={`/studio/${p.id}/build`}
                data-testid="studio-project-card"
                className="flex flex-1 min-w-0 items-center justify-between gap-4"
              >
                <div className="min-w-0">
                  <div className="font-medium truncate">{p.name || t("untitled")}</div>
                  {p.description && (
                    <div className="text-xs text-muted-foreground truncate">{p.description}</div>
                  )}
                </div>
                <div className="flex items-center gap-3 shrink-0 text-xs text-muted-foreground">
                  <span className="rounded-full bg-muted px-2 py-0.5 font-mono">
                    {p.committed_count > 0 ? `v${p.committed_count}` : t("projectDraft")}
                  </span>
                  <span>{t("updatedLabel", { date: formatDate(p.updated_at) })}</span>
                </div>
              </Link>
              <button
                type="button"
                onClick={() => archive(p)}
                data-testid="studio-project-archive"
                aria-label={t("archiveModel")}
                title={t("archiveModel")}
                className="shrink-0 rounded-md p-2 text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
