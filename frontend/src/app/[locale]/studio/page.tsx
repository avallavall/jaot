"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Trash2, ArchiveRestore } from "lucide-react";
import { Link, useRouter } from "@/i18n/navigation";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import type { ProjectListItem } from "@/lib/types";

type View = "active" | "archived";

function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString();
}

/**
 * Studio home — the real "My Models" list, with an Active / Archived toggle.
 * Active models link into their workspace and can be archived (soft-delete, with
 * Undo). Archived models can be restored or permanently deleted (irreversible,
 * behind a confirm dialog). Loading skeleton, empty state, and error+retry.
 */
export default function StudioHomePage() {
  const t = useTranslations("studio");
  const router = useRouter();
  const { activeWorkspaceId } = useAuth();
  const [view, setView] = useState<View>("active");
  const [projects, setProjects] = useState<ProjectListItem[] | null>(null);
  const [error, setError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [pendingDelete, setPendingDelete] = useState<ProjectListItem | null>(null);
  const ws = activeWorkspaceId ?? undefined;

  // State is only set from async callbacks here (never synchronously) so this
  // doesn't trip react-hooks/set-state-in-effect.
  useEffect(() => {
    let active = true;
    api
      .listProjects({ status: view }, ws)
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
  }, [ws, reloadKey, view]);

  const retry = () => {
    setProjects(null);
    setError(false);
    setReloadKey((k) => k + 1);
  };

  // Switching tabs is a user event, so resetting to the loading skeleton here
  // (rather than in the effect) keeps setState out of the effect body.
  const changeView = (next: View) => {
    if (next === view) return;
    setProjects(null);
    setError(false);
    setView(next);
  };

  // Archive (active -> archived) with an Undo that restores it.
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
              .then(() => view === "active" && setProjects((prev) => (prev ? [p, ...prev] : prev)))
              .catch(() => toast.error(t("archiveError")));
          },
        },
      });
    } catch {
      setProjects((prev) => (prev ? [p, ...prev] : prev));
      toast.error(t("archiveError"));
    }
  };

  // Restore (archived -> active).
  const restore = async (p: ProjectListItem) => {
    setProjects((prev) => prev?.filter((x) => x.id !== p.id) ?? prev);
    try {
      await api.updateProject(p.id, { status: "active" }, ws);
      toast.success(t("modelRestored", { name: p.name || t("untitled") }));
    } catch {
      setProjects((prev) => (prev ? [p, ...prev] : prev));
      toast.error(t("actionError"));
    }
  };

  // Permanent delete (archived only, irreversible) — confirmed via the dialog.
  const confirmDelete = async () => {
    const p = pendingDelete;
    setPendingDelete(null);
    if (!p) return;
    setProjects((prev) => prev?.filter((x) => x.id !== p.id) ?? prev);
    try {
      await api.deleteProjectPermanently(p.id, ws);
      toast.success(t("modelDeleted", { name: p.name || t("untitled") }));
    } catch {
      setProjects((prev) => (prev ? [p, ...prev] : prev));
      toast.error(t("actionError"));
    }
  };

  const tabs: Array<{ key: View; label: string }> = [
    { key: "active", label: t("viewActive") },
    { key: "archived", label: t("viewArchived") },
  ];

  return (
    <div className="max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">{t("myModels")}</h1>
          <p className="text-muted-foreground text-sm mt-1">{t("myModelsSubtitle")}</p>
        </div>
        <Button onClick={() => router.push("/studio/new")}>{t("newModel")}</Button>
      </div>

      <div className="mb-4 flex items-center gap-1 border-b">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => changeView(tab.key)}
            aria-pressed={view === tab.key}
            data-testid={`studio-view-${tab.key}`}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm transition-colors",
              view === tab.key
                ? "border-primary font-medium text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {tab.label}
          </button>
        ))}
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
          {view === "archived" ? t("archivedEmpty") : t("myModelsEmpty")}
        </div>
      ) : (
        <ul className="space-y-2">
          {projects.map((p) => (
            <li
              key={p.id}
              className="flex items-center gap-2 rounded-lg border p-4 transition-all hover:border-primary/50 hover:shadow-sm"
            >
              {view === "archived" ? (
                <div className="flex flex-1 min-w-0 items-center justify-between gap-4">
                  <div className="min-w-0">
                    <div className="font-medium truncate">{p.name || t("untitled")}</div>
                    {p.description && (
                      <div className="text-xs text-muted-foreground truncate">{p.description}</div>
                    )}
                  </div>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {t("updatedLabel", { date: formatDate(p.updated_at) })}
                  </span>
                </div>
              ) : (
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
              )}

              {view === "archived" ? (
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => restore(p)}
                    data-testid="studio-project-restore"
                  >
                    <ArchiveRestore className="mr-1 h-4 w-4" />
                    {t("restore")}
                  </Button>
                  <button
                    type="button"
                    onClick={() => setPendingDelete(p)}
                    data-testid="studio-project-delete"
                    aria-label={t("deletePermanently")}
                    title={t("deletePermanently")}
                    className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => archive(p)}
                  data-testid="studio-project-archive"
                  aria-label={t("archiveModel")}
                  title={t("archiveModel")}
                  className="shrink-0 rounded-md p-2 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      <AlertDialog open={pendingDelete !== null} onOpenChange={(o) => !o && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("deleteConfirmTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("deleteConfirmBody", { name: pendingDelete?.name || t("untitled") })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDelete}
              data-testid="studio-delete-confirm"
              className="bg-destructive text-white hover:bg-destructive/90"
            >
              {t("deletePermanently")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
