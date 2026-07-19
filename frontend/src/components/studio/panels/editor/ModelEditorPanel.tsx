"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { AlertCircle, CheckCircle2, Code2, Loader2, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { OptimizationProblem, ValidationResult } from "@/lib/types";
import {
  useModelProjectStore,
  useModelProjectStoreApi,
} from "../../store/useModelProjectStore";
import { scratchProjector } from "../../store/projectors";
import { CANVAS_SCALE_CAP, modelElementCount } from "../../store/model-scale";
import { TooLargeNotice } from "../../TooLargeNotice";
import { parseModelText, type ParseResult, type ShapeField } from "./parse";

const VALIDATE_DEBOUNCE_MS = 500;

/**
 * The Editor (text) sub-lens of Build: a plain monospace textarea over the canonical
 * model serialized as JSON. A valid edit is reprojected onto the canvas and autosaved
 * for free (it flows through `setProblem({source:"scratch"})`); a malformed edit flags
 * this lens' parse error (`parseErrors.scratch`) so solve/commit are blocked, while the
 * canvas/Solve keep the last-good model. Both the flag AND the broken text (store
 * `scratchText`) survive the lens unmounting — switching tab never silently unblocks a
 * solve of a model the user believes they just changed, and coming back re-shows the
 * broken text with its error. Backend `validateProblem` adds live semantic feedback
 * (non-blocking). No external editor dependency.
 */
export function ModelEditorPanel() {
  const t = useTranslations("studio");
  const problem = useModelProjectStore((s) => s.problem);
  const lastSource = useModelProjectStore((s) => s.lastSource);
  const elementCount = useModelProjectStore((s) => modelElementCount(s.problem));
  const tooLarge = elementCount > CANVAS_SCALE_CAP;
  const storeApi = useModelProjectStoreApi();

  // Seed from the retained un-applied text (a broken edit that survived a lens
  // unmount) when there is one, so its error re-shows; otherwise from the model.
  const [text, setText] = useState<string>(
    () => storeApi.getState().scratchText ?? scratchProjector.fromProblem(problem)
  );
  const [parsed, setParsed] = useState<ParseResult>(() => {
    const retained = storeApi.getState().scratchText;
    return retained != null ? parseModelText(retained) : { ok: true, problem };
  });
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [validating, setValidating] = useState(false);
  const validateTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Monotonic token so a slow validation response can never overwrite a newer one.
  const validateSeq = useRef(0);

  // A plain function (not useCallback): it's only invoked from a setTimeout inside
  // handleChange, never passed to a memoized child or a dependency array, so a stable
  // identity buys nothing. Stale-response races are handled by the validateSeq token.
  const runValidate = (p: OptimizationProblem) => {
    const seq = ++validateSeq.current;
    setValidating(true);
    api
      .validateProblem(p)
      .then((res) => {
        if (seq === validateSeq.current) setValidation(res);
      })
      .catch(() => {
        // The validate endpoint is best-effort feedback; a failure must not block editing.
        if (seq === validateSeq.current) setValidation(null);
      })
      .finally(() => {
        if (seq === validateSeq.current) setValidating(false);
      });
  };

  // Re-seed the textarea when the model changes from ANOTHER source (canvas edit,
  // version restore, load) — but never while the user is typing here (lastSource
  // "scratch"), which would clobber the cursor.
  useEffect(() => {
    if (lastSource === "scratch") return;
    // A retained broken text takes precedence over re-seeding: the canonical model
    // has NOT moved since it broke (any `setProblem` would have cleared the retention),
    // so this run is the mount pass and the user's un-applied text must stay visible.
    if (storeApi.getState().scratchText != null) return;
    /* eslint-disable react-hooks/set-state-in-effect -- mirror an external model change
       (canvas / restore / load) into the textarea; intentional derived-state sync */
    setText(scratchProjector.fromProblem(problem));
    setParsed({ ok: true, problem });
    setValidation(null);
    /* eslint-enable react-hooks/set-state-in-effect */
    storeApi.getState().setParseError("scratch", false);
  }, [problem, lastSource, storeApi]);

  // Leaving the editor keeps a broken text's block in place (switching tab must not
  // silently unblock a solve of the last-good model) — the text itself is retained in
  // the store, so coming back re-shows it. Only the in-flight validation is dropped.
  useEffect(
    () => () => {
      if (validateTimer.current) clearTimeout(validateTimer.current);
      validateSeq.current++;
    },
    []
  );

  const handleChange = (value: string) => {
    setText(value);
    const result = parseModelText(value);
    setParsed(result);
    if (validateTimer.current) clearTimeout(validateTimer.current);
    if (result.ok) {
      storeApi.getState().setParseError("scratch", false);
      // Explicit (setProblem also clears it, but no-ops when the parsed model equals
      // the canonical one — the retention must still die once the text is valid).
      storeApi.getState().setScratchText(null);
      storeApi.getState().setProblem(result.problem, { source: "scratch" });
      const p = result.problem;
      validateTimer.current = setTimeout(() => runValidate(p), VALIDATE_DEBOUNCE_MS);
    } else {
      storeApi.getState().setParseError("scratch", true);
      // Retain the un-applied text so it survives this lens unmounting.
      storeApi.getState().setScratchText(value);
      setValidation(null);
    }
  };

  const handleFormat = () => {
    if (!parsed.ok) return;
    setText(scratchProjector.fromProblem(parsed.problem));
  };

  if (tooLarge) {
    return (
      <TooLargeNotice
        testid="studio-editor-too-large"
        icon={<Code2 className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />}
        title={t("editorTooLargeTitle")}
        body={t("editorTooLarge", { count: elementCount })}
      />
    );
  }

  return (
    <div className="flex flex-1 min-h-0 flex-col">
      <div className="flex items-center justify-between gap-3 border-b px-3 py-1.5">
        <p className="min-w-0 truncate text-xs text-muted-foreground">{t("editorHint")}</p>
        <div className="flex items-center gap-2 shrink-0">
          <EditorStatus parsed={parsed} validation={validation} validating={validating} />
          <Button variant="outline" size="sm" onClick={handleFormat} disabled={!parsed.ok}>
            <Wand2 className="mr-1 h-3.5 w-3.5" />
            {t("editorFormat")}
          </Button>
        </div>
      </div>

      <textarea
        data-testid="studio-editor-textarea"
        value={text}
        onChange={(e) => handleChange(e.target.value)}
        spellCheck={false}
        autoComplete="off"
        autoCorrect="off"
        autoCapitalize="off"
        aria-label={t("editorAriaLabel")}
        aria-invalid={!parsed.ok}
        className="flex-1 min-h-0 w-full resize-none bg-transparent px-4 py-3 font-mono text-xs leading-relaxed outline-none"
      />

      {!parsed.ok && (
        <div
          data-testid="studio-editor-error"
          role="alert"
          className="border-t border-destructive/30 bg-destructive/5 px-4 py-2 text-xs text-destructive"
        >
          {parsed.kind === "syntax" ? (
            <span>
              {t("editorInvalid")}: <code className="font-mono">{parsed.detail}</code>
            </span>
          ) : (
            <span>{shapeMessage(t, parsed.field)}</span>
          )}
          <p className="mt-1 opacity-80">{t("lensNotApplied")}</p>
        </div>
      )}

      {/* Defensive: a malformed/legacy validate response (missing `errors`/`warnings`)
          must never crash the whole studio page — reading `.length` on an absent array
          did exactly that on every validated edit. Coalesce to empty. */}
      {parsed.ok && validation && !validation.valid && (validation.errors?.length ?? 0) > 0 && (
        <ul
          data-testid="studio-editor-validation"
          className="border-t border-destructive/30 bg-destructive/5 px-4 py-2 text-xs text-destructive space-y-0.5"
        >
          {(validation.errors ?? []).map((err, i) => (
            <li key={i}>• {err}</li>
          ))}
        </ul>
      )}

      {parsed.ok && validation && (validation.warnings?.length ?? 0) > 0 && (
        <ul className="border-t border-amber-300/40 bg-amber-50 px-4 py-2 text-xs text-amber-800 space-y-0.5 dark:bg-amber-950/40 dark:text-amber-200">
          {(validation.warnings ?? []).map((warn, i) => (
            <li key={i}>• {warn}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function EditorStatus({
  parsed,
  validation,
  validating,
}: {
  parsed: ParseResult;
  validation: ValidationResult | null;
  validating: boolean;
}) {
  const t = useTranslations("studio");
  if (!parsed.ok) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-destructive">
        <AlertCircle className="h-3.5 w-3.5" />
        {t("editorInvalid")}
      </span>
    );
  }
  if (validating) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        {t("editorValidating")}
      </span>
    );
  }
  if (validation && validation.valid) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
        <CheckCircle2 className="h-3.5 w-3.5" />
        {t("editorValid")}
      </span>
    );
  }
  return null;
}

function shapeMessage(
  t: ReturnType<typeof useTranslations>,
  field: ShapeField
): string {
  switch (field) {
    case "object":
      return t("editorShapeObject");
    case "variables":
      return t("editorShapeVariables");
    case "constraints":
      return t("editorShapeConstraints");
    case "objective":
      return t("editorShapeObjective");
  }
}
