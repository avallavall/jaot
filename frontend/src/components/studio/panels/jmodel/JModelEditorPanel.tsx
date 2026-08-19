"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  AlertCircle,
  Boxes,
  CheckCircle2,
  Loader2,
  RefreshCw,
  Sigma,
  Sparkles,
} from "lucide-react";
import { Link } from "@/i18n/navigation";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import type { DslCompileResult } from "@/lib/types";
import { jmodelErrorText } from "@/lib/jmodel-error";
import {
  useModelProjectStore,
  useModelProjectStoreApi,
} from "../../store/useModelProjectStore";
import { nameToAdopt } from "../../adopt-name";
import { useProjectDatasets } from "../../datasets/useProjectDatasets";
import { JModelMathView } from "./JModelMathView";
import { JModelGenerateDialog } from "./JModelGenerateDialog";

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
 * reflects on the canvas/Analyze/Solve and autosaves, while a compile error flags this
 * lens' parse error (`parseErrors.dsl`) so solve/commit are blocked (the canonical model
 * stays last-good). The flag PERSISTS when the lens unmounts — switching tab must not
 * silently unblock a solve of the last-good model — and clears only when the source
 * compiles again or the model is edited from another lens. The source itself is
 * persisted to the draft via `setDraftDslSource` so it survives navigation even when it
 * does not (yet) compile. Lowering is one-way — editing the model elsewhere leaves this
 * source unchanged; the drifted source then shows a notice, is NOT applied, and locks
 * read-only until the user explicitly recompiles (a deliberate replace, never a silent
 * clobber of the newer model). A reload/restore rehydrates the source with its sync
 * state unknowable (`dslMaybeStale`), so it gets the same read-only lock until a
 * successful compile proves it matches — or deliberately replaces — the model.
 */
export function JModelEditorPanel() {
  const t = useTranslations("studio");
  const tError = useTranslations("errors.codes");
  const lastSource = useModelProjectStore((s) => s.lastSource);
  const storeDslSource = useModelProjectStore((s) => s.draftDslSource);
  const modelId = useModelProjectStore((s) => s.modelId);
  const activeDataset = useModelProjectStore((s) => s.activeDataset);
  // The canonical block state. It is the source of truth for "solve is blocked", set by
  // BOTH this lens' local compile AND the provider-level dataset recompile
  // (useActiveDatasetCompile) — e.g. deselecting a dataset under a declaration-only source
  // blocks via the hook without touching the local `result`, so the error box must key off
  // this, not only `result`, or the user sees solve greyed out with no explanation (C2).
  const dslBlocked = useModelProjectStore((s) => s.parseErrors.dsl);
  // A model built elsewhere (canvas / import) that we could de-ground into a draft.
  const hasModel = useModelProjectStore((s) => s.problem.variables.length > 0);
  const storeApi = useModelProjectStoreApi();
  // Named datasets ("scenarios") this source can compile against (§8).
  const { datasets, refresh: refreshDatasets } = useProjectDatasets(
    modelId && modelId !== "new" ? modelId : null
  );

  const [text, setText] = useState<string>(() => storeApi.getState().draftDslSource);
  const [result, setResult] = useState<DslCompileResult | null>(null);
  const [compiling, setCompiling] = useState(false);
  // The split-pane math view is on by default (the flagship "see the notation" view);
  // the user can collapse it back to a plain editor.
  const [showMath, setShowMath] = useState(true);
  // B2: de-grounding the current model into a JModel draft. A DECLINE (the server
  // answered "no verified draft", with its reason) and a FAILURE (transport error,
  // dataset creation failed) are different truths and get different messages.
  const [deriving, setDeriving] = useState(false);
  const [deriveDeclined, setDeriveDeclined] = useState<
    "too_large" | "not_representable" | "error" | "unknown" | null
  >(null);
  const [deriveFailed, setDeriveFailed] = useState(false);
  // B3: the "Generate with AI" dialog.
  const [genOpen, setGenOpen] = useState(false);
  const compileTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Monotonic token so a slow compile response can never overwrite a newer one.
  const compileSeq = useRef(0);
  // Mirrors the on-screen text (updated in the change handler + the sync effect, never
  // during render) so the store-sync effect can skip the user's own keystrokes.
  const textRef = useRef(text);

  // useCallback (unlike the editor's runValidate): this is also called from the
  // mount/unmount effect below, so it must be a stable dependency there.
  const runCompile = useCallback(
    (source: string) => {
      const seq = ++compileSeq.current;
      setCompiling(true);
      api
        // The active dataset is read from the store AT compile time, so the
        // debounced/flushed/mount compiles all use the current selection without
        // threading it through effect dependencies.
        .compileDsl(source, storeApi.getState().activeDataset?.id ?? null)
        .then((res) => {
          if (seq !== compileSeq.current) return;
          setResult(res);
          if (res.ok && res.problem) {
            storeApi.getState().setParseError("dsl", false);
            storeApi.getState().setProblem(res.problem, { source: "dsl" });

            // A JModel source names itself through its objective, so let the
            // project take that name while it is still the placeholder.
            const state = storeApi.getState();
            const adopted = nameToAdopt(state.name, res.problem.name);
            if (adopted && state.modelId && state.modelId !== "new") {
              state.setName(adopted);
              api.updateProject(state.modelId, { name: adopted }).catch(() => {
                /* best-effort rename — never block a compile on it */
              });
            }
          } else {
            storeApi.getState().setParseError("dsl", true);
          }
        })
        .catch(() => {
          // A transport/gate failure must not apply a model or flip the block state.
          // Keep a prior compile error's box visible (so an existing block stays
          // explained rather than invisible); only clear the box if nothing is blocked.
          if (seq !== compileSeq.current) return;
          if (!storeApi.getState().parseErrors.dsl) setResult(null);
        })
        .finally(() => {
          if (seq === compileSeq.current) setCompiling(false);
        });
    },
    [storeApi]
  );

  const handleChange = (value: string) => {
    setText(value);
    textRef.current = value;
    if (deriveDeclined) setDeriveDeclined(null);
    if (deriveFailed) setDeriveFailed(false);
    // Persist the source (dirty) so a work-in-progress model survives navigation even
    // before it compiles.
    storeApi.getState().setDraftDslSource(value, { dirty: true });
    if (compileTimer.current) clearTimeout(compileTimer.current);
    compileTimer.current = null;
    if (!value.trim()) {
      // Empty source: nothing to compile. Clear any error and leave the model as-is.
      compileSeq.current++;
      storeApi.getState().setParseError("dsl", false);
      setResult(null);
      setCompiling(false);
      return;
    }
    // Null the ref when it fires so the unmount flush only re-runs a compile that is
    // genuinely still pending, not one that already ran.
    compileTimer.current = setTimeout(() => {
      compileTimer.current = null;
      runCompile(value);
    }, COMPILE_DEBOUNCE_MS);
  };

  // Sync the textarea when the source changes in the store from OUTSIDE this panel:
  // a load arriving after mount (deep-link / reload race) or a version restore. Guarded
  // by textRef so the user's own typing (which updates the store to the same value)
  // never re-seeds and moves the cursor.
  useEffect(() => {
    if (storeDslSource === textRef.current) return;
    /* eslint-disable react-hooks/set-state-in-effect -- mirror an external source change
       (restore / late load) into the textarea; intentional derived-state sync */
    setText(storeDslSource);
    setResult(null);
    /* eslint-enable react-hooks/set-state-in-effect */
    textRef.current = storeDslSource;
    // Drop BOTH the in-flight compile and a still-pending debounce: they belong to
    // the replaced text, and firing one now would re-flag/apply the old source over
    // the fresh one.
    if (compileTimer.current) clearTimeout(compileTimer.current);
    compileTimer.current = null;
    compileSeq.current++;
    storeApi.getState().setParseError("dsl", false);
  }, [storeDslSource, storeApi]);

  // On mount: a block that persisted from a previous mount (the source still doesn't
  // compile — the flag is never cleared on unmount) has no local error box yet, so
  // re-derive it; the block must stay explained, not invisible. Safe even if the
  // recompile now succeeds: the flag being set proves no other lens touched the model
  // since (setProblem from elsewhere clears it), so applying is what the user asked.
  // On unmount: FLUSH (don't drop) a pending debounced compile — leaving the lens must
  // not skip the compile that decides whether solve stays blocked; its result lands in
  // the provider-owned store even after this panel is gone.
  useEffect(() => {
    if (storeApi.getState().parseErrors.dsl && textRef.current.trim()) {
      runCompile(textRef.current);
    }
    return () => {
      if (compileTimer.current) {
        clearTimeout(compileTimer.current);
        compileTimer.current = null;
        runCompile(textRef.current);
      }
    };
  }, [storeApi, runCompile]);

  // The model was last changed by another lens, so this DSL source may be out of date
  // (lowering is one-way: model → DSL is not reconstructed). A drifted source is NOT
  // the applied model: lock it read-only until the user explicitly opts back in —
  // recompiling it REPLACES the newer model, so that must be a deliberate act, never
  // a silent clobber from a stray keystroke. A reload/restore loses `lastSource`, so
  // the rehydrated source gets the SAME lock via `dslMaybeStale` (sync unknowable)
  // until a successful compile proves it — otherwise one keystroke over a source last
  // applied before a canvas edit would silently clobber the newer model.
  const maybeStale = useModelProjectStore((s) => s.dslMaybeStale);
  const liveDrift = lastSource !== null && lastSource !== "dsl";
  const drifted = liveDrift || maybeStale;
  const stale = drifted && text.trim().length > 0;
  const [editingStale, setEditingStale] = useState(false);
  const readOnly = stale && !editingStale;

  // The opt-in lives for ONE drift episode: when the drift ends (a recompile
  // re-applied this source, or a reload), reset it so the NEXT drift asks again.
  // Adjusted during render — self-terminating (the set makes the condition false).
  if (!drifted && editingStale) setEditingStale(false);

  const handleRecompile = () => {
    setEditingStale(true);
    if (compileTimer.current) clearTimeout(compileTimer.current);
    compileTimer.current = null;
    runCompile(textRef.current);
  };

  // Switching the dataset recompiles the source against the new data right away —
  // an explicit user act, so no debounce (and a stale lock disables the selector).
  const handleDatasetChange = (datasetId: string) => {
    const row = datasetId ? datasets.find((d) => d.id === datasetId) : undefined;
    storeApi.getState().setActiveDataset(row ? { id: row.id, name: row.name } : null);
    if (compileTimer.current) clearTimeout(compileTimer.current);
    compileTimer.current = null;
    // The provider-level useActiveDatasetCompile already recompiles on an
    // active-dataset change for the normal (source === "dsl") case — compiling
    // here too would double-fire (harmless but wasteful). Only compile directly
    // in the DRIFTED window, which that hook deliberately skips: picking a
    // dataset after opting back into a drifted source is an explicit "apply it"
    // act the provider hook won't perform.
    if (drifted && textRef.current.trim()) runCompile(textRef.current);
  };

  // B2: reconstruct a JModel draft from the canonical model (built on the canvas or
  // imported). The server declines (source === null) when no compact structure
  // round-trips; we surface that honestly rather than load a fake. On success the
  // draft becomes the source and is applied like a normal edit (compile → canonical).
  // For a persisted project the derive is SPLIT: the source is the pure formulation
  // and the data lands in an auto-created, auto-selected project dataset — the
  // model/data separation JModel is for (no 22k-number wall in the editor).
  const handleDerive = () => {
    setDeriving(true);
    setDeriveDeclined(null);
    setDeriveFailed(false);
    const persistedId = modelId && modelId !== "new" ? modelId : null;
    api
      .degroundDsl(storeApi.getState().problem, persistedId !== null)
      .then(async (res) => {
        if (!res.source) {
          setDeriveDeclined(res.reason ?? "unknown");
          return;
        }
        if (res.dataset && persistedId) {
          const base = t("jmodelDeriveDatasetName");
          const taken = new Set(datasets.map((d) => d.name));
          let name = base;
          for (let n = 2; taken.has(name); n++) name = `${base} ${n}`;
          const row = await api.createProjectDataset(persistedId, {
            name,
            data_json: res.dataset,
          });
          // Select it BEFORE compiling so the declaration-only source grounds.
          storeApi.getState().setActiveDataset({ id: row.id, name: row.name });
          refreshDatasets();
        }
        setEditingStale(true); // deriving is an explicit opt-in over a drifted source
        setText(res.source);
        textRef.current = res.source;
        storeApi.getState().setDraftDslSource(res.source, { dirty: true });
        if (compileTimer.current) clearTimeout(compileTimer.current);
        compileTimer.current = null;
        runCompile(res.source);
      })
      // A transport/server/dataset-creation failure is NOT a decline — saying
      // "your model has no structure" about a network error would be a lie.
      .catch(() => setDeriveFailed(true))
      .finally(() => setDeriving(false));
  };

  // B3: an AI-generated source lands in the editor exactly like a derived draft —
  // an explicit opt-in over any drift, applied through the normal compile flow.
  const applyGeneratedSource = (source: string) => {
    setEditingStale(true);
    setText(source);
    textRef.current = source;
    storeApi.getState().setDraftDslSource(source, { dirty: true });
    if (compileTimer.current) clearTimeout(compileTimer.current);
    compileTimer.current = null;
    runCompile(source);
  };

  // Offer "derive a draft" exactly when the JModel source is NOT the current model:
  // the editor is empty, or it drifted because another lens changed the model.
  const canDerive = hasModel && (drifted || !text.trim());

  return (
    <div className="flex flex-1 min-h-0 flex-col">
      <div className="flex items-center justify-between gap-3 border-b px-3 py-1.5">
        <p className="min-w-0 truncate text-xs text-muted-foreground">{t("jmodelHint")}</p>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            data-testid="studio-jmodel-generate-open"
            onClick={() => setGenOpen(true)}
            className="h-6 gap-1 px-1.5 text-xs text-primary hover:text-primary"
          >
            <Sparkles className="h-3.5 w-3.5" />
            {t("jmodelGenerate")}
          </Button>
          {datasets.length > 0 && (
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              {t("jmodelDatasetLabel")}
              <select
                data-testid="studio-jmodel-dataset"
                value={activeDataset?.id ?? ""}
                onChange={(e) => handleDatasetChange(e.target.value)}
                disabled={readOnly}
                className="max-w-[12rem] truncate rounded-md border bg-transparent px-1.5 py-0.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              >
                <option value="">{t("jmodelNoDataset")}</option>
                {datasets.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <Button
            variant="ghost"
            size="sm"
            data-testid="studio-jmodel-math-toggle"
            aria-pressed={showMath}
            title={showMath ? t("jmodelMathHide") : t("jmodelMathShow")}
            onClick={() => setShowMath((v) => !v)}
            className={cn(
              "h-6 gap-1 px-1.5 text-xs",
              showMath ? "text-foreground" : "text-muted-foreground"
            )}
          >
            <Sigma className="h-3.5 w-3.5" />
            {t("jmodelMathToggle")}
          </Button>
          <JModelStatus result={result} compiling={compiling} />
        </div>
      </div>

      {stale && (
        <div className="flex items-center justify-between gap-3 border-b border-amber-300/40 bg-amber-50 px-4 py-1.5 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          <span>{t(liveDrift ? "jmodelStale" : "jmodelStaleReload")}</span>
          {readOnly && (
            <div className="flex shrink-0 items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                data-testid="studio-jmodel-recompile"
                onClick={handleRecompile}
                className="h-6 border-amber-400/60 bg-transparent px-2 text-xs text-amber-900 hover:bg-amber-100 dark:text-amber-100 dark:hover:bg-amber-900"
              >
                <RefreshCw className="mr-1 h-3 w-3" />
                {t("jmodelRecompile")}
              </Button>
              <Button
                variant="outline"
                size="sm"
                data-testid="studio-jmodel-derive"
                onClick={handleDerive}
                disabled={deriving}
                className="h-6 border-amber-400/60 bg-transparent px-2 text-xs text-amber-900 hover:bg-amber-100 dark:text-amber-100 dark:hover:bg-amber-900"
              >
                {deriving ? (
                  <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                ) : (
                  <Boxes className="mr-1 h-3 w-3" />
                )}
                {t("jmodelDerive")}
              </Button>
            </div>
          )}
        </div>
      )}

      {!stale && !text.trim() && canDerive && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/30 px-4 py-2 text-xs text-muted-foreground">
          <span>{t("jmodelDeriveHint")}</span>
          <Button
            variant="outline"
            size="sm"
            data-testid="studio-jmodel-derive"
            onClick={handleDerive}
            disabled={deriving}
            className="h-6 shrink-0 px-2 text-xs"
          >
            {deriving ? (
              <Loader2 className="mr-1 h-3 w-3 animate-spin" />
            ) : (
              <Boxes className="mr-1 h-3 w-3" />
            )}
            {t("jmodelDerive")}
          </Button>
        </div>
      )}

      {deriveDeclined && (
        <div
          data-testid="studio-jmodel-derive-declined"
          className="border-b border-amber-300/40 bg-amber-50 px-4 py-1.5 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
        >
          {t(
            deriveDeclined === "too_large"
              ? "jmodelDeriveDeclinedTooLarge"
              : deriveDeclined === "not_representable"
                ? "jmodelDeriveDeclinedNotRepresentable"
                : "jmodelDeriveDeclined"
          )}
        </div>
      )}

      {deriveFailed && (
        <div
          data-testid="studio-jmodel-derive-failed"
          className="border-b border-destructive/30 bg-destructive/5 px-4 py-1.5 text-xs text-destructive"
        >
          {t("jmodelDeriveFailed")}
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          <textarea
            data-testid="studio-jmodel-textarea"
            value={text}
            onChange={(e) => handleChange(e.target.value)}
            readOnly={readOnly}
            spellCheck={false}
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            placeholder={PLACEHOLDER_EXAMPLE}
            aria-label={t("jmodelAriaLabel")}
            aria-invalid={result ? !result.ok : false}
            className={cn(
              "flex-1 min-h-0 w-full resize-none bg-transparent px-4 py-3 font-mono text-xs leading-relaxed outline-none",
              readOnly && "cursor-not-allowed opacity-60"
            )}
          />

          {(dslBlocked || (result && !result.ok)) && (
            <div
              data-testid="studio-jmodel-error"
              role="alert"
              className="border-t border-destructive/30 bg-destructive/5 px-4 py-2 text-xs text-destructive"
            >
              <span>
                {t("jmodelInvalid")}:{" "}
                {/* Prefer the specific compiler message; fall back to a generic one when the
                    block was set by the provider-level recompile (no local `result`). */}
                <code className="font-mono">
                  {result && !result.ok && result.error
                    ? jmodelErrorText(result.error, tError)
                    : t("jmodelBlockedGeneric")}
                </code>
                {result && !result.ok && typeof result.error?.position === "number" && (
                  <span className="opacity-70"> (pos {result.error.position})</span>
                )}
              </span>
              <p className="mt-1 opacity-80">{t("lensNotApplied")}</p>
              {/* S4 cross-link: a data-shaped error (declaration without values/members,
                  dataset/model mismatch — those messages all name "dataset"), OR a block
                  set by the provider recompile (a dataset (de)selection), is fixed in the
                  Datos tab, not by editing the source. */}
              {modelId &&
                modelId !== "new" &&
                (!(result && !result.ok && result.error) ||
                  /dataset|has no (values|members)/i.test(result.error!.message)) && (
                  <p className="mt-1">
                    <Link
                      href={`/studio/${modelId}/data`}
                      className="font-medium underline underline-offset-2"
                      data-testid="studio-jmodel-goto-data"
                    >
                      {t("jmodelGoToData")}
                    </Link>
                  </p>
                )}
            </div>
          )}
        </div>

        {showMath && (
          <div className="min-w-0 flex-1 border-l">
            <JModelMathView source={text} active={showMath} />
          </div>
        )}
      </div>

      <JModelGenerateDialog
        open={genOpen}
        onOpenChange={setGenOpen}
        currentSource={text}
        onGenerated={applyGeneratedSource}
      />
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
