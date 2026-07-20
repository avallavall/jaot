"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { AlertCircle, Loader2 } from "lucide-react";
import "katex/dist/katex.min.css";
import { BlockMath } from "react-katex";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { DslLatexLine, DslLatexModel } from "@/lib/types";

const LATEX_DEBOUNCE_MS = 400;

interface JModelMathViewProps {
  /** The current JModel source (the on-screen editor text). */
  source: string;
  /** Whether the pane is visible — it fetches only when active, so a hidden pane
   * costs nothing. */
  active: boolean;
}

/**
 * The right half of the JModel split-pane: the source rendered as symbolic math
 * (KaTeX), fetched from the parse-only `POST /dsl/latex`. The backend walks the AST
 * BEFORE grounding, so the indexed objective, ∀-quantified constraint families and
 * variable domains stay symbolic instead of flattening to thousands of scalar rows.
 *
 * It keeps the LAST successfully-rendered model on screen while the user is mid-edit:
 * a source that momentarily fails to parse dims the notation and shows a hint rather
 * than flickering to an error box on every keystroke (the editor's own error box owns
 * the authoritative message).
 */
export function JModelMathView({ source, active }: JModelMathViewProps) {
  const t = useTranslations("studio");
  const [model, setModel] = useState<DslLatexModel | null>(null);
  const [parseError, setParseError] = useState(false);
  const [loading, setLoading] = useState(false);
  // Monotonic token so a slow response can never overwrite a newer render.
  const seq = useRef(0);

  useEffect(() => {
    if (!active) return;
    if (!source.trim()) {
      seq.current++;
      /* eslint-disable react-hooks/set-state-in-effect -- reset derived render state
         when the source empties; there is nothing to fetch */
      setModel(null);
      setParseError(false);
      setLoading(false);
      /* eslint-enable react-hooks/set-state-in-effect */
      return;
    }
    const mySeq = ++seq.current;
    setLoading(true);
    const timer = setTimeout(() => {
      api
        .latexDsl(source)
        .then((res) => {
          if (mySeq !== seq.current) return;
          if (res.ok && res.model) {
            setModel(res.model);
            setParseError(false);
          } else {
            // Keep the last good render visible; just flag it stale.
            setParseError(true);
          }
        })
        .catch(() => {
          // Transport / gate failure: leave the last render untouched.
          if (mySeq !== seq.current) return;
        })
        .finally(() => {
          if (mySeq === seq.current) setLoading(false);
        });
    }, LATEX_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [source, active]);

  const empty = !source.trim();
  const hasModel = model !== null && !isEmptyModel(model);

  return (
    <div
      data-testid="studio-jmodel-math"
      className="flex h-full min-h-0 flex-col overflow-auto bg-muted/20"
    >
      <div className="flex items-center justify-between gap-2 border-b px-3 py-1.5">
        <p className="min-w-0 truncate text-xs font-medium text-muted-foreground">
          {t("jmodelMathTitle")}
        </p>
        {loading && <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" />}
      </div>

      <div className="min-h-0 flex-1 px-4 py-3">
        {empty ? (
          <p className="text-xs text-muted-foreground">{t("jmodelMathEmpty")}</p>
        ) : !hasModel ? (
          <p className="text-xs text-muted-foreground">
            {parseError ? t("jmodelMathInvalid") : t("jmodelCompiling")}
          </p>
        ) : (
          <div className={cn("space-y-5", parseError && "opacity-50")}>
            {parseError && (
              <p className="flex items-center gap-1.5 text-xs text-amber-600 dark:text-amber-400">
                <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                {t("jmodelMathInvalid")}
              </p>
            )}
            {model!.objective && (
              <MathSection title={t("jmodelMathObjective")} lines={[model!.objective]} />
            )}
            {model!.constraints.length > 0 && (
              <MathSection title={t("jmodelMathSubjectTo")} lines={model!.constraints} withLabels />
            )}
            {model!.variables.length > 0 && (
              <MathSection title={t("jmodelMathDomains")} lines={model!.variables} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function isEmptyModel(model: DslLatexModel): boolean {
  return !model.objective && model.constraints.length === 0 && model.variables.length === 0;
}

function MathSection({
  title,
  lines,
  withLabels = false,
}: {
  title: string;
  lines: DslLatexLine[];
  withLabels?: boolean;
}) {
  return (
    <div>
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h4>
      <div className="space-y-2">
        {lines.map((line, i) => (
          <div key={i} className="overflow-x-auto">
            <SafeBlockMath latex={line.latex} />
            {withLabels && line.label && (
              <p className="mt-0.5 text-[11px] text-muted-foreground">({line.label})</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * A KaTeX block that degrades to a monospace fallback if the (backend-generated,
 * so normally valid) LaTeX ever fails to parse — a rendering error must never blank
 * the pane.
 */
function SafeBlockMath({ latex }: { latex: string }) {
  return (
    <BlockMath
      math={latex}
      renderError={() => (
        <pre className="overflow-x-auto rounded bg-muted p-2 font-mono text-xs">{latex}</pre>
      )}
    />
  );
}
