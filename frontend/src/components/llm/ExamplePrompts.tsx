"use client";

import { Truck, Users, TrendingUp, Package } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

interface ExamplePromptsProps {
  onSelect: (prompt: string) => void;
}

interface PromptCard {
  icon: ReactNode;
  key: string;
}

const EXAMPLES: PromptCard[] = [
  { icon: <Truck className="w-5 h-5 text-blue-500" />, key: "shipping" },
  { icon: <Users className="w-5 h-5 text-green-500" />, key: "scheduling" },
  { icon: <TrendingUp className="w-5 h-5 text-purple-500" />, key: "portfolio" },
  { icon: <Package className="w-5 h-5 text-orange-500" />, key: "binPacking" },
];

/**
 * Clickable example prompts shown when the chat is empty.
 * Reduces blank-page anxiety by giving users starter optimization problems.
 */
export function ExamplePrompts({ onSelect }: ExamplePromptsProps) {
  const t = useTranslations("builder");

  return (
    <div className="flex flex-col items-center justify-center h-full px-4">
      <div className="text-center mb-6">
        <h3 className="text-lg font-semibold text-foreground">
          {t("llm.examplePrompts.title")}
        </h3>
        <p className="text-sm text-muted-foreground mt-1">
          {t("llm.examplePrompts.subtitle")}
        </p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-lg">
        {EXAMPLES.map((example) => {
          const text = t(`llm.examplePrompts.${example.key}`);
          return (
            <button
              key={example.key}
              onClick={() => onSelect(text)}
              className="flex items-start gap-3 p-3 rounded-lg border border-border bg-card text-left text-sm transition-colors hover:bg-accent hover:border-accent-foreground/20"
            >
              <span className="flex-shrink-0 mt-0.5">{example.icon}</span>
              <span className="text-foreground/80">{text}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
