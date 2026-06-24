"use client";

import type { Formulation } from "@/lib/llm-types";
import Markdown from "react-markdown";
import { useTranslations } from "next-intl";

interface TextViewProps {
  formulation: Formulation;
}

type TranslateFunc = (key: string, values?: Record<string, string | number | Date>) => string;

/**
 * Convert a Formulation to a structured markdown string.
 */
function formulationToMarkdown(f: Formulation, t: TranslateFunc): string {
  const lines: string[] = [];

  lines.push(`# ${f.problem_name}`);
  lines.push("");
  if (f.summary) {
    lines.push(f.summary);
    lines.push("");
  }

  lines.push(`## ${t("llm.formulation.variables")}`);
  lines.push("");
  for (const v of f.variables) {
    const lb = v.lower_bound !== null ? String(v.lower_bound) : "-inf";
    const ub = v.upper_bound !== null ? String(v.upper_bound) : "+inf";
    lines.push(`- **${v.name}** (${v.type}): ${v.description} [bounds: ${lb} to ${ub}]`);
  }
  lines.push("");

  lines.push(`## ${t("llm.formulation.constraints")}`);
  lines.push("");
  for (const c of f.constraints) {
    lines.push(`- **${c.name}**: \`${c.expression}\` — ${c.description}`);
  }
  lines.push("");

  lines.push(`## ${t("llm.formulation.objective")}`);
  lines.push("");
  const senseLabel = f.objective.sense === "minimize" ? t("llm.formulation.minimize") : t("llm.formulation.maximize");
  lines.push(
    `**${senseLabel}**: \`${f.objective.expression}\` — ${f.objective.description}`
  );

  return lines.join("\n");
}

/**
 * Markdown rendering of a formulation.
 * Converts formulation data to structured markdown and renders it.
 */
export function TextView({ formulation }: TextViewProps) {
  const t = useTranslations("builder");
  const markdown = formulationToMarkdown(formulation, t);

  return (
    <div className="prose prose-sm dark:prose-invert max-w-none">
      <Markdown>{markdown}</Markdown>
    </div>
  );
}
