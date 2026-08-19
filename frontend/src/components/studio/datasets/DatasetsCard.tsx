"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import { Database, Pencil, Plus, Trash2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { api } from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";
import { describeJsonError } from "@/lib/json-error";
import type { DslInspectResult, ProjectDatasetSummary } from "@/lib/types";
import { useModelProjectStore } from "../store/useModelProjectStore";
import { useProjectDatasets } from "./useProjectDatasets";
import { buildDatasetSkeleton } from "./dataset-skeleton";
import {
  checkDatasetAgainstDeclarations,
  type DatasetCheckMessage,
} from "./dataset-validation";
import { tableFromJson, tableToJson, type TableModel } from "./dataset-table";
import { DatasetTableEditor } from "./DatasetTableEditor";

// Seed shown in the editor for a NEW dataset — the JModelData JSON shape.
const NEW_DATASET_TEMPLATE = `{
  "sets": {
    "I": ["a", "b", "c"]
  },
  "params": {
    "cap": 10,
    "w": { "a": 2, "b": 3, "c": 4 }
  }
}`;

interface EditorState {
  /** null = creating; otherwise the dataset being edited. */
  id: string | null;
  name: string;
  description: string;
  text: string;
}

/**
 * The Analyze card for §8 Scenarios: the project's named datasets (set members +
 * param values for a declaration-only JModel). List / create / edit / delete, plus
 * "use" — which marks the dataset the JModel lens compiles against (store
 * `activeDataset`, shown on the Solve tab). Rendered only when the JAOT_DSL
 * feature is on and the project is persisted.
 */
export function DatasetsCard() {
  const t = useTranslations("studio");
  const modelId = useModelProjectStore((s) => s.modelId);
  const activeDataset = useModelProjectStore((s) => s.activeDataset);
  const setActiveDataset = useModelProjectStore((s) => s.setActiveDataset);
  // S2a: the skeleton derives from the draft JModel source's real declarations.
  const draftDslSource = useModelProjectStore((s) => s.draftDslSource);
  const isPersisted = !!modelId && modelId !== "new";
  const { datasets, refresh } = useProjectDatasets(isPersisted ? modelId : null);

  const [editor, setEditor] = useState<EditorState | null>(null);
  const [saving, setSaving] = useState(false);
  const [skeletonLoading, setSkeletonLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<ProjectDatasetSummary | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // S2b: the values editor has two views over the SAME text — raw JSON and a
  // structured table. The table model lives here while that view is open (a
  // re-parse per keystroke would normalize half-typed input out from under the
  // user); every table edit serializes back to `editor.text`.
  const [view, setView] = useState<"json" | "table">("json");
  const [tableModel, setTableModel] = useState<TableModel | null>(null);
  const enterTableView = () => {
    if (!editor) return;
    const model = tableFromJson(editor.text);
    if (model === null) {
      toast.info(t("datasetTableUnparseable"));
      return;
    }
    setTableModel(model);
    setView("table");
  };
  const handleTableChange = (model: TableModel) => {
    setTableModel(model);
    const text = tableToJson(model);
    setEditor((prev) => (prev ? { ...prev, text } : prev));
  };

  // S5: live dataset↔model guidance. The declarations are fetched ONCE per dialog
  // open (they depend on the SOURCE, not the dataset text); every edit then runs a
  // pure local check — no round-trip per keystroke. Server compile stays the truth.
  const dialogOpen = editor !== null;
  const editorText = editor?.text ?? "";
  const [decls, setDecls] = useState<DslInspectResult | null>(null);
  const [checkMessages, setCheckMessages] = useState<DatasetCheckMessage[] | null>(null);
  useEffect(() => {
    if (!dialogOpen || !draftDslSource.trim()) {
      setDecls(null);
      return;
    }
    let cancelled = false;
    api
      .inspectDsl(draftDslSource)
      .then((r) => {
        if (!cancelled) setDecls(r);
      })
      .catch(() => {
        /* guidance only — the save path still validates server-side */
      });
    return () => {
      cancelled = true;
    };
  }, [dialogOpen, draftDslSource]);
  useEffect(() => {
    if (!dialogOpen || decls === null) {
      setCheckMessages(null);
      return;
    }
    const id = setTimeout(
      () => setCheckMessages(checkDatasetAgainstDeclarations(editorText, decls)),
      400,
    );
    return () => clearTimeout(id);
  }, [dialogOpen, editorText, decls]);

  if (!isPersisted) return null;

  const openCreate = () => {
    setView("json");
    setEditor({ id: null, name: "", description: "", text: NEW_DATASET_TEMPLATE });
  };

  const openEdit = async (row: ProjectDatasetSummary) => {
    try {
      // The list is compact — fetch the full values on demand.
      const full = await api.getProjectDataset(modelId, row.id);
      setView("json");
      setEditor({
        id: full.id,
        name: full.name,
        description: full.description ?? "",
        text: JSON.stringify(full.data_json, null, 2),
      });
    } catch (err: unknown) {
      toast.error(getErrorMessage(err, t("datasetLoadFailed")));
    }
  };

  const handleSave = async () => {
    if (!editor) return;
    let data: Record<string, unknown>;
    try {
      data = JSON.parse(editor.text) as Record<string, unknown>;
    } catch (err: unknown) {
      // Never interpolate the engine's own message. Its one useful shape quotes
      // the broken text back at whoever typed it, in English, inside whatever
      // language the page is in. The position is the part a reader can act on.
      const parseError = describeJsonError(err);
      toast.error(
        parseError.kind === "positioned"
          ? t("datasetInvalidJsonAt", { line: parseError.line!, column: parseError.column! })
          : parseError.kind === "truncated"
            ? t("datasetInvalidJsonTruncated")
            : t("datasetInvalidJson"),
      );
      return;
    }
    setSaving(true);
    try {
      if (editor.id === null) {
        await api.createProjectDataset(modelId, {
          name: editor.name,
          description: editor.description || null,
          data_json: data,
        });
      } else {
        const updated = await api.updateProjectDataset(modelId, editor.id, {
          name: editor.name,
          description: editor.description || null,
          data_json: data,
        });
        // Keep the workspace-wide selection label in sync with a rename.
        if (activeDataset?.id === updated.id) {
          setActiveDataset({ id: updated.id, name: updated.name });
        }
      }
      toast.success(t("datasetSaved"));
      setEditor(null);
      refresh();
    } catch (err: unknown) {
      // 422 carries the compiler-grade validation message; 409 a duplicate name.
      toast.error(getErrorMessage(err, t("datasetSaveFailed")));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!confirmDelete) return;
    try {
      await api.deleteProjectDataset(modelId, confirmDelete.id);
      // A deleted dataset must not linger as the active compile target.
      if (activeDataset?.id === confirmDelete.id) setActiveDataset(null);
      toast.success(t("datasetDeleted"));
      refresh();
    } catch (err: unknown) {
      toast.error(getErrorMessage(err, t("datasetDeleteFailed")));
    } finally {
      setConfirmDelete(null);
    }
  };

  const toggleUse = (row: ProjectDatasetSummary) => {
    if (activeDataset?.id === row.id) setActiveDataset(null);
    else setActiveDataset({ id: row.id, name: row.name });
  };

  // S2c: parse an uploaded .dat / .json / .csv into the editor (server-side
  // preview — nothing is stored until the user saves through the normal create).
  const handleImportFile = async (file: File) => {
    if (!editor) return;
    setImporting(true);
    try {
      const preview = await api.importProjectDataset(modelId, file);
      setEditor((prev) =>
        prev
          ? {
              ...prev,
              text: JSON.stringify(preview.data_json, null, 2),
              // A name the user already typed wins over the filename suggestion.
              name: prev.name.trim() ? prev.name : preview.suggested_name,
            }
          : prev,
      );
      // A wholesale replacement is clearest reviewed as raw JSON (re-enter
      // the table view to keep editing structurally).
      setView("json");
    } catch (err: unknown) {
      // 422 carries the parser message incl. the character position.
      toast.error(getErrorMessage(err, t("datasetImportFailed")));
    } finally {
      setImporting(false);
    }
  };

  // S2a: pre-fill the editor with the model's REAL declared symbols (sets → [],
  // scalar params → 0, indexed → {}). Deterministic — /dsl/inspect parses only,
  // so it works for declaration-only sources that don't compile yet.
  const handleSkeleton = async () => {
    if (!editor || !draftDslSource.trim()) return;
    setSkeletonLoading(true);
    try {
      const inspect = await api.inspectDsl(draftDslSource);
      if (!inspect.ok) {
        toast.error(
          t("datasetSkeletonParseError", { error: inspect.error?.message ?? "" }),
        );
        return;
      }
      const text = buildDatasetSkeleton(inspect);
      if (text === null) {
        toast.info(t("datasetSkeletonNothing"));
        return;
      }
      // Functional update: name/description typed while the request was in flight
      // must survive — only the values text is the requested replacement. A closed
      // dialog (prev === null) stays closed.
      setEditor((prev) => (prev ? { ...prev, text } : prev));
      setView("json");
    } catch (err: unknown) {
      toast.error(getErrorMessage(err, t("datasetSkeletonFailed")));
    } finally {
      setSkeletonLoading(false);
    }
  };

  return (
    <section className="mt-6 rounded-lg border p-4" data-testid="studio-datasets-card">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold">
            <Database className="h-4 w-4 text-muted-foreground" />
            {t("datasetsTitle")}
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">{t("datasetsHint")}</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={openCreate}
          data-testid="studio-dataset-new"
          className="shrink-0"
        >
          <Plus className="mr-1 h-3.5 w-3.5" />
          {t("datasetNew")}
        </Button>
      </div>

      {datasets.length === 0 ? (
        <p className="mt-3 text-xs text-muted-foreground">{t("datasetsEmpty")}</p>
      ) : (
        <ul className="mt-3 divide-y">
          {datasets.map((row) => {
            const inUse = activeDataset?.id === row.id;
            return (
              <li
                key={row.id}
                className="flex items-center justify-between gap-3 py-2"
                data-testid="studio-dataset-row"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">
                    {row.name}
                    {inUse && (
                      <span className="ml-2 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
                        {t("datasetInUse")}
                      </span>
                    )}
                  </p>
                  {row.description && (
                    <p className="truncate text-xs text-muted-foreground">{row.description}</p>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    variant={inUse ? "secondary" : "outline"}
                    size="sm"
                    onClick={() => toggleUse(row)}
                    data-testid="studio-dataset-use"
                  >
                    {inUse ? t("datasetStopUsing") : t("datasetUse")}
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t("datasetEdit")}
                    onClick={() => void openEdit(row)}
                    data-testid="studio-dataset-edit"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t("datasetDelete")}
                    onClick={() => setConfirmDelete(row)}
                    data-testid="studio-dataset-delete"
                  >
                    <Trash2 className="h-3.5 w-3.5 text-destructive" />
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <Dialog open={editor !== null} onOpenChange={(open) => !open && setEditor(null)}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>
              {editor?.id === null ? t("datasetNew") : t("datasetEdit")}
            </DialogTitle>
          </DialogHeader>
          {editor && (
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-xs font-medium" htmlFor="dataset-name">
                  {t("datasetName")}
                </label>
                <input
                  id="dataset-name"
                  data-testid="studio-dataset-name"
                  value={editor.name}
                  onChange={(e) => setEditor({ ...editor, name: e.target.value })}
                  className="w-full rounded-md border bg-transparent px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium" htmlFor="dataset-desc">
                  {t("datasetDescription")}
                </label>
                <input
                  id="dataset-desc"
                  value={editor.description}
                  onChange={(e) => setEditor({ ...editor, description: e.target.value })}
                  className="w-full rounded-md border bg-transparent px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                />
              </div>
              <div>
                <div className="mb-1 flex items-center justify-between gap-2">
                  <label className="block text-xs font-medium" htmlFor="dataset-json">
                    {t("datasetValues")}
                  </label>
                  <div className="flex items-center gap-1">
                    {/* S2b: two views over the same text — raw JSON and a table. */}
                    <div className="mr-1 flex overflow-hidden rounded border text-xs">
                      <button
                        type="button"
                        onClick={() => setView("json")}
                        data-testid="studio-dataset-view-json"
                        aria-pressed={view === "json"}
                        className={`px-2 py-0.5 ${view === "json" ? "bg-muted font-medium" : "text-muted-foreground hover:text-foreground"}`}
                      >
                        JSON
                      </button>
                      <button
                        type="button"
                        onClick={enterTableView}
                        data-testid="studio-dataset-view-table"
                        aria-pressed={view === "table"}
                        className={`border-l px-2 py-0.5 ${view === "table" ? "bg-muted font-medium" : "text-muted-foreground hover:text-foreground"}`}
                      >
                        {t("datasetTableView")}
                      </button>
                    </div>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".dat,.json,.csv"
                      className="hidden"
                      data-testid="studio-dataset-import-input"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        // Reset so re-choosing the same file fires onChange again.
                        e.target.value = "";
                        if (file) void handleImportFile(file);
                      }}
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-6 px-2 text-xs"
                      onClick={() => fileInputRef.current?.click()}
                      disabled={importing}
                      data-testid="studio-dataset-import"
                    >
                      <Upload className="mr-1 h-3 w-3" />
                      {t("datasetImport")}
                    </Button>
                    {draftDslSource.trim() && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-6 px-2 text-xs"
                        onClick={() => void handleSkeleton()}
                        disabled={skeletonLoading}
                        data-testid="studio-dataset-skeleton"
                      >
                        {t("datasetSkeleton")}
                      </Button>
                    )}
                  </div>
                </div>
                {view === "table" && tableModel ? (
                  <DatasetTableEditor model={tableModel} onModelChange={handleTableChange} />
                ) : (
                  <textarea
                    id="dataset-json"
                    data-testid="studio-dataset-json"
                    value={editor.text}
                    onChange={(e) => setEditor({ ...editor, text: e.target.value })}
                    spellCheck={false}
                    rows={12}
                    className="w-full resize-y rounded-md border bg-transparent px-2 py-1.5 font-mono text-xs leading-relaxed focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                )}
                {/* S5: live guidance against the model's declarations. */}
                {checkMessages && (
                  <div data-testid="studio-dataset-check" className="mt-1 space-y-0.5">
                    {checkMessages.slice(0, 6).map((m, i) => (
                      <p
                        key={`${m.key}-${i}`}
                        className={
                          m.level === "ok"
                            ? "text-xs text-emerald-600 dark:text-emerald-400"
                            : "text-xs text-amber-600 dark:text-amber-400"
                        }
                      >
                        {m.level === "ok" ? "✓ " : "• "}
                        {t(m.key, m.values)}
                      </p>
                    ))}
                    {checkMessages.length > 6 && (
                      <p className="text-xs text-muted-foreground">
                        {t("datasetCheckMore", { count: checkMessages.length - 6 })}
                      </p>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditor(null)} disabled={saving}>
              {t("datasetCancel")}
            </Button>
            <Button
              onClick={() => void handleSave()}
              disabled={saving || !editor?.name.trim()}
              data-testid="studio-dataset-save"
            >
              {t("datasetSave")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={confirmDelete !== null}
        onOpenChange={(open) => !open && setConfirmDelete(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("datasetDeleteConfirmTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("datasetDeleteConfirmBody", { name: confirmDelete?.name ?? "" })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("datasetCancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => void handleDelete()}
              data-testid="studio-dataset-delete-confirm"
              className="bg-destructive text-white hover:bg-destructive/90"
            >
              {t("datasetDelete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
