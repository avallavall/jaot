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
import { useDateFormat } from "@/hooks/useDateFormat";

type View = "active" | "archived";
type Scope = "all" | "mine";

/** Rows per request — the backend's own default for this endpoint. */
const PAGE_SIZE = 50;
type Confirm =
  | { kind: "single"; project: ProjectListItem }
  | { kind: "bulk"; ids: string[] }
  | null;

/**
 * Studio home — the org's models (collaborative, org-wide), with Active/Archived
 * tabs and a Mine / Whole-org scope filter. Each row shows who created it. Active
 * models link into their workspace and can be archived (with Undo). Archived
 * models can be restored or permanently deleted — one at a time or in bulk via
 * multi-select.
 */
export default function StudioHomePage() {
  const t = useTranslations("studio");
  const { day: formatDate } = useDateFormat();
  const router = useRouter();
  const { activeWorkspaceId } = useAuth();
  const [view, setView] = useState<View>("active");
  const [scope, setScope] = useState<Scope>("all");
  const [projects, setProjects] = useState<ProjectListItem[] | null>(null);
  const [error, setError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const ws = activeWorkspaceId ?? undefined;

  // The backend answers at most PAGE_SIZE rows and says nothing about the rest,
  // so this page used to stop at 50 models in silence — no search, no way on.
  // Search runs server-side (`q`), because filtering what already arrived can
  // only ever find the first 50.
  useEffect(() => {
    const handle = setTimeout(() => setSearch(query.trim()), 300);
    return () => clearTimeout(handle);
  }, [query]);

  // State is only set from async callbacks here (never synchronously) so this
  // doesn't trip react-hooks/set-state-in-effect.
  useEffect(() => {
    let active = true;
    api
      .listProjects(
        { status: view, mine: scope === "mine", q: search || undefined, limit: PAGE_SIZE },
        ws,
      )
      .then((p) => {
        if (active) {
          setProjects(p);
          // A full page means there is probably another one. Asking for it and
          // getting nothing is cheaper than an extra count query per keystroke.
          setHasMore(p.length === PAGE_SIZE);
          setError(false);
        }
      })
      .catch(() => {
        if (active) setError(true);
      });
    return () => {
      active = false;
    };
  }, [ws, reloadKey, view, scope, search]);

  const loadMore = async () => {
    if (loadingMore || !projects) return;
    setLoadingMore(true);
    try {
      const next = await api.listProjects(
        {
          status: view,
          mine: scope === "mine",
          q: search || undefined,
          skip: projects.length,
          limit: PAGE_SIZE,
        },
        ws,
      );
      setProjects((prev) => [...(prev ?? []), ...next]);
      setHasMore(next.length === PAGE_SIZE);
    } catch {
      setHasMore(false);
    } finally {
      setLoadingMore(false);
    }
  };

  const retry = () => {
    setProjects(null);
    setError(false);
    setReloadKey((k) => k + 1);
  };

  // View/scope changes are user events, so resetting to the loading skeleton +
  // clearing the selection here keeps setState out of the effect body.
  const changeView = (next: View) => {
    if (next === view) return;
    setProjects(null);
    setError(false);
    setSelected(new Set());
    setView(next);
  };
  const changeScope = (next: Scope) => {
    if (next === scope) return;
    setProjects(null);
    setError(false);
    setSelected(new Set());
    setScope(next);
  };

  const drop = (ids: Set<string>) =>
    setProjects((prev) => prev?.filter((x) => !ids.has(x.id)) ?? prev);
  const readd = (items: ProjectListItem[]) =>
    setProjects((prev) => (prev ? [...items, ...prev] : prev));

  // Archive (active -> archived) with an Undo that restores it.
  //
  // Archiving also withdraws the model from the marketplace, because an archived
  // model refuses every write and could never be updated again. Undo restores the
  // model and NOT the listing, so a published model gets a message that says so.
  const archive = async (p: ProjectListItem) => {
    drop(new Set([p.id]));
    try {
      await api.archiveProject(p.id, ws);
      const key = p.listing_status === "published" ? "modelArchivedWithdrawn" : "modelArchived";
      toast.success(t(key, { name: p.name || t("untitled") }), {
        action: {
          label: t("undo"),
          onClick: () => {
            api
              .updateProject(p.id, { status: "active" }, ws)
              .then(() => view === "active" && readd([p]))
              .catch(() => toast.error(t("archiveError")));
          },
        },
      });
    } catch {
      readd([p]);
      toast.error(t("archiveError"));
    }
  };

  const restoreOne = async (p: ProjectListItem) => {
    drop(new Set([p.id]));
    try {
      await api.updateProject(p.id, { status: "active" }, ws);
      toast.success(t("modelRestored", { name: p.name || t("untitled") }));
    } catch {
      readd([p]);
      toast.error(t("actionError"));
    }
  };

  const toggleOne = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const allSelected = !!projects && projects.length > 0 && projects.every((p) => selected.has(p.id));
  const toggleAll = () =>
    setSelected(allSelected ? new Set() : new Set((projects ?? []).map((p) => p.id)));

  const selectedItems = () => (projects ?? []).filter((p) => selected.has(p.id));

  const restoreSelected = async () => {
    const items = selectedItems();
    if (!items.length) return;
    const ids = new Set(items.map((p) => p.id));
    drop(ids);
    setSelected(new Set());
    const results = await Promise.allSettled(
      items.map((p) => api.updateProject(p.id, { status: "active" }, ws))
    );
    const failed = items.filter((_, i) => results[i].status === "rejected");
    if (failed.length) {
      readd(failed);
      toast.error(t("actionError"));
    } else {
      toast.success(t("bulkRestored", { count: items.length }));
    }
  };

  // Single + bulk permanent delete share the confirm dialog (`confirm` state).
  const runConfirmedDelete = async () => {
    const c = confirm;
    setConfirm(null);
    if (!c) return;
    const items =
      c.kind === "single" ? [c.project] : (projects ?? []).filter((p) => c.ids.includes(p.id));
    if (!items.length) return;
    const ids = new Set(items.map((p) => p.id));
    drop(ids);
    setSelected(new Set());
    const results = await Promise.allSettled(
      items.map((p) => api.deleteProjectPermanently(p.id, ws))
    );
    const failed = items.filter((_, i) => results[i].status === "rejected");
    if (failed.length) {
      readd(failed);
      toast.error(
        c.kind === "single" ? t("actionError") : t("bulkDeleteError", { count: failed.length })
      );
    } else if (c.kind === "single") {
      toast.success(t("modelDeleted", { name: items[0].name || t("untitled") }));
    } else {
      toast.success(t("bulkDeleted", { count: items.length }));
    }
  };

  const tabs: Array<{ key: View; label: string }> = [
    { key: "active", label: t("viewActive") },
    { key: "archived", label: t("viewArchived") },
  ];
  const scopes: Array<{ key: Scope; label: string }> = [
    { key: "all", label: t("viewAll") },
    { key: "mine", label: t("viewMine") },
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

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b">
        <div className="flex items-center gap-1">
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
        <div className="mb-1.5 flex items-center gap-2">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("searchPlaceholder")}
            aria-label={t("searchPlaceholder")}
            data-testid="studio-search"
            className="h-8 w-44 rounded-md border bg-background px-2.5 text-xs outline-none focus:border-primary"
          />
        <div className="inline-flex rounded-md border p-0.5 text-xs">
          {scopes.map((s) => (
            <button
              key={s.key}
              type="button"
              onClick={() => changeScope(s.key)}
              aria-pressed={scope === s.key}
              data-testid={`studio-scope-${s.key}`}
              className={cn(
                "rounded px-2.5 py-1 transition-colors",
                scope === s.key
                  ? "bg-muted font-medium text-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {s.label}
            </button>
          ))}
        </div>
        </div>
      </div>

      {/* Bulk action bar (archived view, multi-select). */}
      {view === "archived" && projects && projects.length > 0 && (
        <div className="mb-2 flex items-center gap-3 rounded-md bg-muted/40 px-3 py-2 text-sm">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={toggleAll}
              data-testid="studio-select-all"
              className="h-4 w-4 accent-primary"
            />
            {t("selectAll")}
          </label>
          {selected.size > 0 && (
            <>
              <span className="text-muted-foreground">{t("selectedCount", { count: selected.size })}</span>
              <div className="ml-auto flex items-center gap-2">
                <Button variant="outline" size="sm" onClick={restoreSelected}>
                  <ArchiveRestore className="mr-1 h-4 w-4" />
                  {t("restore")}
                </Button>
                <Button
                  size="sm"
                  onClick={() => setConfirm({ kind: "bulk", ids: [...selected] })}
                  data-testid="studio-delete-selected"
                  className="bg-destructive text-white hover:bg-destructive/90"
                >
                  <Trash2 className="mr-1 h-4 w-4" />
                  {t("deletePermanently")}
                </Button>
              </div>
            </>
          )}
        </div>
      )}

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
          {search
            ? t("searchEmpty", { query: search })
            : view === "archived"
              ? t("archivedEmpty")
              : t("myModelsEmpty")}
        </div>
      ) : (
        <ul className="space-y-2">
          {projects.map((p) => (
            <li
              key={p.id}
              className="flex items-center gap-2 rounded-lg border p-4 transition-all hover:border-primary/50 hover:shadow-sm"
            >
              {view === "archived" && (
                <input
                  type="checkbox"
                  checked={selected.has(p.id)}
                  onChange={() => toggleOne(p.id)}
                  aria-label={t("selectRow", { name: p.name || t("untitled") })}
                  data-testid="studio-row-select"
                  className="h-4 w-4 shrink-0 accent-primary"
                />
              )}

              {view === "archived" ? (
                <div className="flex flex-1 min-w-0 items-center justify-between gap-4">
                  <div className="min-w-0">
                    <div className="font-medium truncate">{p.name || t("untitled")}</div>
                    <div className="text-xs text-muted-foreground truncate">
                      {p.created_by_name ? t("createdBy", { name: p.created_by_name }) : null}
                    </div>
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
                    <div className="text-xs text-muted-foreground truncate">
                      {[p.description, p.created_by_name && t("createdBy", { name: p.created_by_name })]
                        .filter(Boolean)
                        .join(" · ")}
                    </div>
                  </div>
                  <div className="flex items-center gap-3 shrink-0 text-xs text-muted-foreground">
                    {/* Which models are on the marketplace, without opening each one. */}
                    {p.listing_status === "published" && (
                      <span className="rounded-full bg-primary/10 px-2 py-0.5 text-primary">
                        {t("listingPublished")}
                      </span>
                    )}
                    {p.listing_status === "unpublished" && (
                      <span className="rounded-full bg-muted px-2 py-0.5">
                        {t("listingWithdrawn")}
                      </span>
                    )}
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
                    onClick={() => restoreOne(p)}
                    data-testid="studio-project-restore"
                  >
                    <ArchiveRestore className="mr-1 h-4 w-4" />
                    {t("restore")}
                  </Button>
                  <button
                    type="button"
                    onClick={() => setConfirm({ kind: "single", project: p })}
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

      {/* The list stopped at 50 with nothing to say so; now it says so. */}
      {hasMore && projects && projects.length > 0 && (
        <div className="mt-4 flex justify-center">
          <Button
            variant="outline"
            size="sm"
            onClick={loadMore}
            disabled={loadingMore}
            data-testid="studio-load-more"
          >
            {loadingMore ? t("loadingMore") : t("loadMore")}
          </Button>
        </div>
      )}

      <AlertDialog open={confirm !== null} onOpenChange={(o) => !o && setConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {confirm?.kind === "bulk"
                ? t("bulkDeleteConfirmTitle", { count: confirm.ids.length })
                : t("deleteConfirmTitle")}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {confirm?.kind === "bulk"
                ? t("bulkDeleteConfirmBody")
                : t("deleteConfirmBody", { name: confirm?.project.name || t("untitled") })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={runConfirmedDelete}
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
