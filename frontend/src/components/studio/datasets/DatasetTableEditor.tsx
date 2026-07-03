"use client";

import { useTranslations } from "next-intl";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { TableIndexedParam, TableModel } from "./dataset-table";

interface DatasetTableEditorProps {
  model: TableModel;
  /** Receives the edited model; the parent serializes it back to the JSON text. */
  onModelChange: (model: TableModel) => void;
}

/**
 * The structured "table" view of the dataset dialog (S2b): sets as member
 * lists, scalar params as a number field, indexed params as index/value rows
 * with add/remove. The model lives in the PARENT while the view is open (a
 * re-parse per keystroke would normalize half-typed input out from under the
 * user); the parent serializes every change back to the JSON text, so the raw
 * view and the live S5 check always see the same data.
 */
export function DatasetTableEditor({ model, onModelChange }: DatasetTableEditorProps) {
  const t = useTranslations("studio");

  const commit = (next: TableModel) => onModelChange(next);

  const updateSet = (index: number, membersText: string) => {
    const next = structuredClone(model);
    next.sets[index].membersText = membersText;
    commit(next);
  };

  const updateScalar = (index: number, value: string) => {
    const next = structuredClone(model);
    const param = next.params[index];
    if (param.kind === "scalar") param.value = value;
    commit(next);
  };

  const updateRow = (
    paramIndex: number,
    rowIndex: number,
    partIndex: number | "value",
    value: string,
  ) => {
    const next = structuredClone(model);
    const param = next.params[paramIndex] as TableIndexedParam;
    if (partIndex === "value") param.rows[rowIndex].value = value;
    else param.rows[rowIndex].parts[partIndex] = value;
    commit(next);
  };

  const addRow = (paramIndex: number) => {
    const next = structuredClone(model);
    const param = next.params[paramIndex] as TableIndexedParam;
    param.rows.push({ parts: Array<string>(param.arity).fill(""), value: "" });
    commit(next);
  };

  const removeRow = (paramIndex: number, rowIndex: number) => {
    const next = structuredClone(model);
    const param = next.params[paramIndex] as TableIndexedParam;
    param.rows.splice(rowIndex, 1);
    commit(next);
  };

  const cellClass =
    "w-full rounded border bg-transparent px-1.5 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-ring";

  return (
    <div
      data-testid="studio-dataset-table"
      className="max-h-80 space-y-3 overflow-y-auto rounded-md border p-2"
    >
      {model.sets.length === 0 && model.params.length === 0 && (
        <p className="p-2 text-xs text-muted-foreground">{t("datasetTableEmpty")}</p>
      )}

      {model.sets.map((s, i) => (
        <div key={s.name}>
          <p className="mb-1 text-xs font-semibold">
            set <code className="font-mono">{s.name}</code>
          </p>
          <input
            value={s.membersText}
            onChange={(e) => updateSet(i, e.target.value)}
            placeholder={t("datasetTableMembers")}
            data-testid="studio-dataset-table-set"
            className={cellClass}
          />
        </div>
      ))}

      {model.params.map((p, pi) =>
        p.kind === "scalar" ? (
          <div key={p.name}>
            <p className="mb-1 text-xs font-semibold">
              param <code className="font-mono">{p.name}</code>
            </p>
            <input
              type="number"
              value={p.value}
              onChange={(e) => updateScalar(pi, e.target.value)}
              data-testid="studio-dataset-table-scalar"
              className={cellClass}
            />
          </div>
        ) : (
          <div key={p.name}>
            <div className="mb-1 flex items-center justify-between">
              <p className="text-xs font-semibold">
                param <code className="font-mono">{p.name}</code>
                <span className="ml-1 font-normal text-muted-foreground">
                  ({t("datasetTableArity", { count: p.arity })})
                </span>
              </p>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-5 px-1.5 text-xs"
                onClick={() => addRow(pi)}
                data-testid="studio-dataset-table-add-row"
              >
                <Plus className="mr-0.5 h-3 w-3" />
                {t("datasetTableAddRow")}
              </Button>
            </div>
            <div className="space-y-1">
              {p.rows.map((row, ri) => (
                <div key={ri} className="flex items-center gap-1">
                  {row.parts.map((part, xi) => (
                    <input
                      key={xi}
                      value={part}
                      onChange={(e) => updateRow(pi, ri, xi, e.target.value)}
                      placeholder={`i${xi + 1}`}
                      data-testid="studio-dataset-table-index"
                      className={cellClass}
                    />
                  ))}
                  <input
                    type="number"
                    value={row.value}
                    onChange={(e) => updateRow(pi, ri, "value", e.target.value)}
                    placeholder={t("datasetTableValue")}
                    data-testid="studio-dataset-table-value"
                    className={cellClass}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 shrink-0"
                    aria-label={t("datasetTableRemoveRow")}
                    onClick={() => removeRow(pi, ri)}
                  >
                    <Trash2 className="h-3 w-3 text-destructive" />
                  </Button>
                </div>
              ))}
            </div>
          </div>
        ),
      )}
    </div>
  );
}
