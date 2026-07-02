"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type { DslCompileResult } from "@/lib/types";
import {
  useModelProjectStore,
  useModelProjectStoreApi,
} from "../../store/useModelProjectStore";

const COMPILE_DEBOUNCE_MS = 500;

// Example JModel shown as the textarea placeholder. It is language-neutral source
// code, so it lives here rather than in i18n (its braces would also break ICU parsing).
const PLACEHOLDER_EXAMPLE = `set I := {a, b, c};
param w{I} := a 2, b 3, c 4;
var x{I} binary;
maximize obj: sum{i in I} w[i] * x[i];
subject to pick_two: sum{i in I} x[i] <= 2;`;

/**
 * The JModel (DSL) sub-lens of Build: a plain monospace textarea over the declarative
 * source. Every debounced edit is compiled server-side (`POST /dsl/compile`); a
 * successful compile flows the lowered model through `setProblem({source:"dsl"})` so it
 * reflects on the canvas/Analyze/Solve and autosaves, while a compile error is held
 * locally and flags `jmodelParseError` so solve/commit are blocked (the canonical model
 * stays last-good). The source itself is persisted to the draft via `setDraftDslSource`
 * so it survives navigation even when it does not (yet) compile. Lowering is one-way —
 * editing the model elsewhere leaves this source unchanged (a notice flags the drift).
 */
export function JModelEditorPanel() {
  const t = useTranslations("studio");
  const lastSource = useModelProjectStore((s) => s.lastSource);
  const storeApi = useModelProjectStoreApi();

  const [text, setText] = useState<string>(() => storeApi.getState().draftDslSource);
  const [result, setResult] = useState<DslCompileResult | null>(null);
  const [compiling, setCompiling] = useState(false);
  const compileTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Monotonic token so a slow compile response can never overwrite a newer one.
  const compileSeq = useRef(0);

  const runCompile = (source: string) => {
    const seq = ++compileSeq.current;
    setCompiling(true);
    api
      .compileDsl(source)
      .then((res) => {
        if (seq !== compileSeq.current) return;
        setResult(res);
        if (res.ok && res.problem) {
          storeApi.getState().setJmodelParseError(false);
          storeApi.getState().setProblem(res.problem, { source: "dsl" });
        } else {
          storeApi.getState().setJmodelParseError(true);
        }
      })
      .catch(() => {
        // A transport/gate failure must not block editing or apply a stale model.
        if (seq === compileSeq.current) setResult(null);
      })
      .finally(() => {
        if (seq === compileSeq.current) setCompiling(false);
      });
  };

  const handleChange = (value: string) => {
    setText(value);
    // Persist the source (dirty) so a work-in-progress model survives navigation even
    // before it compiles.
    storeApi.getState().setDraftDslSource(value, { dirty: true });
    if (compileTimer.current) clearTimeout(compileTimer.current);
    if (!value.trim()) {
      // Empty source: nothing to compile. Clear any error and leave the model as-is.
      compileSeq.current++;
      storeApi.getState().setJmodelParseError(false);
      setResult(null);
      setCompiling(false);
      return;
    }
    compileTimer.current = setTimeout(() => runCompile(value), COMPILE_DEBOUNCE_MS);
  };

  // Leaving the lens abandons any broken source's block (the canonical model is always
  // last-good-valid) and drops any in-flight compile.
  useEffect(
    () => () => {
      if (compileTimer.current) clearTimeout(compileTimer.current);
      compileSeq.current++;
      storeApi.getState().setJmodelParseError(false);
    },
    [storeApi]
  );

  // The model was last changed by another lens, so this DSL source may be out of date
  // (lowering is one-way: model → DSL is not reconstructed).
  const stale = lastSource !== null && lastSource !== "dsl" && text.trim().length > 0;

  return (
    <div className="flex flex-1 min-h-0 flex-col">
      <div className="flex items-center justify-between gap-3 border-b px-3 py-1.5">
        <p className="min-w-0 truncate text-xs text-muted-foreground">{t("jmodelHint")}</p>
        <JModelStatus result={result} compiling={compiling} />
      </div>

      {stale && (
        <div className="border-b border-amber-300/40 bg-amber-50 px-4 py-1.5 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          {t("jmodelStale")}
        </div>
      )}

      <textarea
        data-testid="studio-jmodel-textarea"
        value={text}
        onChange={(e) => handleChange(e.target.value)}
        spellCheck={false}
        autoComplete="off"
        autoCorrect="off"
        autoCapitalize="off"
        placeholder={PLACEHOLDER_EXAMPLE}
        aria-label={t("jmodelAriaLabel")}
        aria-invalid={result ? !result.ok : false}
        className="flex-1 min-h-0 w-full resize-none bg-transparent px-4 py-3 font-mono text-xs leading-relaxed outline-none"
      />

      {result && !result.ok && result.error && (
        <div
          data-testid="studio-jmodel-error"
          role="alert"
          className="border-t border-destructive/30 bg-destructive/5 px-4 py-2 text-xs text-destructive"
        >
          <span>
            {t("jmodelInvalid")}: <code className="font-mono">{result.error.message}</code>
            {typeof result.error.position === "number" && (
              <span className="opacity-70"> (pos {result.error.position})</span>
            )}
          </span>
        </div>
      )}
    </div>
  );
}

function JModelStatus({
  result,
  compiling,
}: {
  result: DslCompileResult | null;
  compiling: boolean;
}) {
  const t = useTranslations("studio");
  if (compiling) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        {t("jmodelCompiling")}
      </span>
    );
  }
  if (result && !result.ok) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-destructive">
        <AlertCircle className="h-3.5 w-3.5" />
        {t("jmodelInvalid")}
      </span>
    );
  }
  if (result && result.ok) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
        <CheckCircle2 className="h-3.5 w-3.5" />
        {t("jmodelValid")}
      </span>
    );
  }
  return null;
}
