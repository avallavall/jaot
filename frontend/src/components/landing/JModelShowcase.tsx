"use client";

import { useTranslations } from "next-intl";
import "katex/dist/katex.min.css";
import { BlockMath } from "react-katex";
import { cn } from "@/lib/utils";
import { JMODEL_SHOWCASE } from "./data/jmodelShowcase";

/**
 * JModel, the way the studio shows it: source on one side, symbolic notation on
 * the other.
 *
 * This was the largest hole in the page. JModel is not an optional extra — the
 * JAOT_DSL flag was retired precisely because it IS the product — and the home
 * page did not mention it once.
 *
 * Everything here comes from the real compiler (scripts/gen_landing_jmodel.py):
 * `latexify` renders the model BEFORE grounding, which is why the sums and the ∀
 * stay symbolic instead of flattening into thousands of scalar rows, and
 * `compile_jmodel` produced the two grounded sizes. Same KaTeX renderer the
 * studio uses, so what a visitor sees is what they get.
 *
 * Client component only because react-katex is; the LaTeX itself is static and
 * committed, so nothing is fetched or computed at runtime.
 */
export function JModelShowcase() {
  const t = useTranslations("public.jmodel");
  const { source, objective, constraints, variables, scales } = JMODEL_SHOWCASE;
  const [small, large] = scales;

  return (
    <div className="grid gap-px overflow-hidden border border-border bg-border lg:grid-cols-2">
      {/* The source: what you write. */}
      <div className="bg-card p-6 sm:p-8">
        <h3 className="mb-5 font-mono text-[0.6875rem] uppercase tracking-widest text-muted-foreground">
          {t("sourceHeading")}
        </h3>
        <pre className="overflow-x-auto font-mono text-xs leading-relaxed text-foreground">
          <code>
            {source.map((line, i) => (
              <span key={i} className="block">
                {line || " "}
              </span>
            ))}
          </code>
        </pre>
      </div>

      {/* The notation: what it means. Three formulas against thirteen lines of
          source leaves a hole at the bottom of this column, so the heading stays
          aligned with its opposite number and the maths centres in what is left. */}
      <div className="flex min-w-0 flex-col bg-card p-6 sm:p-8">
        <h3 className="mb-5 font-mono text-[0.6875rem] uppercase tracking-widest text-muted-foreground">
          {t("notationHeading")}
        </h3>

        {/* The overrides live in globals.css under .jmodel-notation, NOT as
            arbitrary variants here: katex.min.css is imported by this component,
            so Next injects it after the Tailwind utilities and they lose on
            order — the same trap sonner's stylesheet set. min-w-0 lets the long
            constraint scroll instead of clipping, which a flex child will not do
            on its own. */}
        <div
          className={cn(
            "jmodel-notation flex min-w-0 flex-1 flex-col justify-center gap-4",
            // Sized so the longest line — the capacity constraint with its two
            // quantifiers — fits the column outright. .katex-display scrolls
            // rather than clips, but a formula you have to drag reads as broken.
            "text-[0.82rem] text-foreground sm:text-[0.88rem]",
          )}
        >
          {objective ? <BlockMath math={objective.latex} /> : null}
          {constraints.map((line) => (
            <div key={line.label ?? line.latex}>
              <BlockMath math={line.latex} />
            </div>
          ))}
          {variables.map((line) => (
            <div key={line.label ?? line.latex} className="opacity-70">
              <BlockMath math={line.latex} />
            </div>
          ))}
        </div>
      </div>

      {/* The point: the source does not grow when the data does. */}
      <div className="bg-card px-6 py-5 sm:px-8 lg:col-span-2">
        <div className="flex flex-wrap items-baseline gap-x-10 gap-y-3">
          <Scale
            label={t("scaleSmall", {
              products: small.products,
              resources: small.resources,
              weeks: small.weeks,
            })}
            value={t("scaleResult", {
              variables: small.variables,
              constraints: small.constraints,
            })}
          />
          <Scale
            label={t("scaleLarge", {
              products: large.products,
              resources: large.resources,
              weeks: large.weeks,
            })}
            value={t("scaleResult", {
              variables: large.variables,
              constraints: large.constraints,
            })}
            highlight
          />
          <p className="ml-auto max-w-md text-sm leading-relaxed text-muted-foreground">
            {t("scaleNote", { lines: JMODEL_SHOWCASE.sourceLines })}
          </p>
        </div>
      </div>
    </div>
  );
}

interface ScaleProps {
  label: string;
  value: string;
  highlight?: boolean;
}

function Scale({ label, value, highlight }: ScaleProps) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="font-mono text-[0.625rem] uppercase tracking-widest text-muted-foreground">
        {label}
      </span>
      <span
        className={cn(
          "font-mono text-sm tabular-nums",
          highlight ? "text-primary" : "text-foreground",
        )}
      >
        {value}
      </span>
    </div>
  );
}
