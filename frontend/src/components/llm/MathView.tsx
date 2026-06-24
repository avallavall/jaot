"use client";

import { useState } from "react";
import type { Formulation } from "@/lib/llm-types";
import "katex/dist/katex.min.css";
import { BlockMath } from "react-katex";
import { useTranslations } from "next-intl";

interface MathViewProps {
  formulation: Formulation;
}

/**
 * Convert a plain-text math expression to LaTeX notation.
 *
 * Handles common patterns from Claude's output:
 * - `*` -> implicit multiplication (removed or replaced with \cdot)
 * - `<=` -> \leq, `>=` -> \geq
 * - `!=` -> \neq
 * - `sum(...)` -> \sum
 * - Variable subscripts: x_1, x_2, etc. (already LaTeX-compatible)
 */
export function expressionToLatex(expr: string): string {
  let latex = expr;

  // Replace comparison operators first (before individual chars)
  latex = latex.replace(/<=/g, "\\leq ");
  latex = latex.replace(/>=/g, "\\geq ");
  latex = latex.replace(/!=/g, "\\neq ");

  // Replace multiplication: `3*x` -> `3 \\cdot x`
  latex = latex.replace(/\*/g, " \\cdot ");

  // Replace sum(...) with \sum notation
  latex = latex.replace(/\bsum\b/gi, "\\sum");

  // Replace common function names
  latex = latex.replace(/\bmin\b/gi, "\\min");
  latex = latex.replace(/\bmax\b/gi, "\\max");
  latex = latex.replace(/\babs\b/gi, "\\left|");

  // Replace sqrt
  latex = latex.replace(/\bsqrt\(([^)]+)\)/g, "\\sqrt{$1}");

  // Clean up multiple spaces
  latex = latex.replace(/\s+/g, " ").trim();

  return latex;
}

/**
 * Safely render a LaTeX block with fallback to raw text on error.
 */
function SafeBlockMath({ latex, fallback }: { latex: string; fallback: string }) {
  const [hasError, setHasError] = useState(false);

  if (hasError) {
    return (
      <pre className="font-mono text-sm bg-muted p-2 rounded overflow-x-auto">
        {fallback}
      </pre>
    );
  }

  return (
    <div
      onError={() => setHasError(true)}
      className="overflow-x-auto"
    >
      <BlockMath math={latex} errorColor="#ef4444" />
    </div>
  );
}

/**
 * LaTeX rendering of a formulation using KaTeX.
 * Converts plain-text expressions to LaTeX notation.
 */
export function MathView({ formulation }: MathViewProps) {
  const t = useTranslations("builder");
  return (
    <div className="space-y-6">
      <h3 className="text-base font-semibold">{formulation.problem_name}</h3>

      <div>
        <h4 className="text-sm font-semibold text-muted-foreground mb-3">{t("llm.formulation.variables")}</h4>
        <div className="space-y-1">
          {formulation.variables.map((v, i) => {
            let domainLatex: string;
            if (v.type === "binary") {
              domainLatex = `${v.name} \\in \\{0, 1\\}`;
            } else if (v.type === "integer") {
              const lb = v.lower_bound !== null ? String(v.lower_bound) : "-\\infty";
              const ub = v.upper_bound !== null ? String(v.upper_bound) : "+\\infty";
              domainLatex = `${v.name} \\in \\mathbb{Z}, \\quad ${lb} \\leq ${v.name} \\leq ${ub}`;
            } else {
              const lb = v.lower_bound !== null ? String(v.lower_bound) : "-\\infty";
              const ub = v.upper_bound !== null ? String(v.upper_bound) : "+\\infty";
              domainLatex = `${v.name} \\in \\mathbb{R}, \\quad ${lb} \\leq ${v.name} \\leq ${ub}`;
            }
            return (
              <SafeBlockMath
                key={i}
                latex={domainLatex}
                fallback={`${v.name}: ${v.type} [${v.lower_bound ?? "-inf"}, ${v.upper_bound ?? "+inf"}]`}
              />
            );
          })}
        </div>
      </div>

      <div>
        <h4 className="text-sm font-semibold text-muted-foreground mb-3">{t("llm.formulation.objective")}</h4>
        <SafeBlockMath
          latex={`\\${formulation.objective.sense === "minimize" ? "min" : "max"} \\quad ${expressionToLatex(formulation.objective.expression)}`}
          fallback={`${formulation.objective.sense}: ${formulation.objective.expression}`}
        />
      </div>

      <div>
        <h4 className="text-sm font-semibold text-muted-foreground mb-3">
          {t("llm.formulation.subjectTo", { count: formulation.constraints.length })}
        </h4>
        <div className="space-y-1">
          {formulation.constraints.map((c, i) => (
            <div key={i}>
              <SafeBlockMath
                latex={expressionToLatex(c.expression)}
                fallback={c.expression}
              />
              {c.name && (
                <p className="text-xs text-muted-foreground text-center -mt-1 mb-2">
                  ({c.name})
                </p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
