"use client";

import * as React from "react";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from "@/components/ui/popover";
import { getTermDefinition } from "@/lib/optimization-terms";
import { useGuidance } from "@/contexts/GuidanceContext";
import { useTranslations } from "next-intl";

interface TooltipSingletonContextValue {
  openId: string | null;
  setOpenId: (id: string | null) => void;
}

export const TooltipSingletonContext =
  React.createContext<TooltipSingletonContextValue | null>(null);

export function TooltipSingletonProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [openId, setOpenId] = React.useState<string | null>(null);
  const value = React.useMemo(() => ({ openId, setOpenId }), [openId]);
  return (
    <TooltipSingletonContext.Provider value={value}>
      {children}
    </TooltipSingletonContext.Provider>
  );
}

function useTooltipSingleton() {
  return React.useContext(TooltipSingletonContext);
}

interface ConceptTooltipProps {
  termKey: string;
  children: React.ReactNode;
  side?: "top" | "bottom" | "left" | "right";
}

/**
 * Wraps children with a popover showing a plain-English explanation of an
 * optimization term from the glossary.
 *
 * Features:
 * - Click to pin open, click outside to dismiss
 * - Hover to preview (300ms delay), auto-close on mouse leave
 * - Singleton: only one tooltip open at a time (via TooltipSingletonProvider)
 * - Formula toggle for credit-related terms
 * - Expert skill level renders children only (no tooltip)
 * - Definitions and examples loaded from translation JSON (glossary namespace)
 */
export function ConceptTooltip({
  termKey,
  children,
  side = "top",
}: ConceptTooltipProps) {
  const { skillLevel } = useGuidance();
  const termDef = getTermDefinition(termKey);
  const tg = useTranslations("glossary");
  const id = React.useId();
  const singleton = useTooltipSingleton();

  // Convert kebab-case termKey to camelCase for glossary JSON lookup
  const glossaryKey = termKey.replace(/-([a-z])/g, (_, c: string) => c.toUpperCase());

  // Local state fallback when no singleton provider is present
  const [localOpen, setLocalOpen] = React.useState(false);

  const isOpen = singleton ? singleton.openId === id : localOpen;
  const setOpen = React.useCallback(
    (open: boolean) => {
      if (singleton) {
        singleton.setOpenId(open ? id : null);
      } else {
        setLocalOpen(open);
      }
    },
    [singleton, id]
  );

  // Track whether the popover was opened via click (pin) vs hover
  const isClickedRef = React.useRef(false);
  const hoverOpenTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const hoverCloseTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  const [showFormula, setShowFormula] = React.useState(false);

  // Reset formula toggle when popover closes
  React.useEffect(() => {
    if (!isOpen) {
      setShowFormula(false);
      isClickedRef.current = false;
    }
  }, [isOpen]);

  // Expert users or unknown terms: no tooltip wrapper
  if (skillLevel === "expert" || !termDef) {
    return <>{children}</>;
  }

  // Get translated definition and example
  const definition = tg(`${glossaryKey}.definition`);
  const hasExample = tg.has(`${glossaryKey}.example`);
  const example = hasExample ? tg(`${glossaryKey}.example`) : undefined;

  const clearTimers = () => {
    if (hoverOpenTimerRef.current) {
      clearTimeout(hoverOpenTimerRef.current);
      hoverOpenTimerRef.current = null;
    }
    if (hoverCloseTimerRef.current) {
      clearTimeout(hoverCloseTimerRef.current);
      hoverCloseTimerRef.current = null;
    }
  };

  const handleTriggerMouseEnter = () => {
    if (isClickedRef.current) return; // Already pinned via click
    clearTimers();
    hoverOpenTimerRef.current = setTimeout(() => {
      setOpen(true);
    }, 300);
  };

  const handleTriggerMouseLeave = () => {
    if (isClickedRef.current) return; // Pinned, don't close on hover
    clearTimers();
    hoverCloseTimerRef.current = setTimeout(() => {
      setOpen(false);
    }, 150);
  };

  const handleContentMouseEnter = () => {
    if (isClickedRef.current) return;
    clearTimers();
  };

  const handleContentMouseLeave = () => {
    if (isClickedRef.current) return;
    clearTimers();
    hoverCloseTimerRef.current = setTimeout(() => {
      setOpen(false);
    }, 150);
  };

  const handleTriggerClick = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    clearTimers();
    if (isOpen && isClickedRef.current) {
      // Already pinned, unpin/close
      isClickedRef.current = false;
      setOpen(false);
    } else {
      isClickedRef.current = true;
      setOpen(true);
    }
  };

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      clearTimers();
      isClickedRef.current = false;
      setOpen(false);
    }
  };

  return (
    <Popover open={isOpen} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="inline border-b border-dashed border-muted-foreground/50 cursor-help bg-transparent p-0 text-inherit font-inherit text-left leading-inherit"
          onClick={handleTriggerClick}
          onMouseEnter={handleTriggerMouseEnter}
          onMouseLeave={handleTriggerMouseLeave}
        >
          {children}
        </button>
      </PopoverTrigger>
      <PopoverContent
        side={side}
        className="w-auto max-w-xs"
        onMouseEnter={handleContentMouseEnter}
        onMouseLeave={handleContentMouseLeave}
      >
        <div className="space-y-1">
          <p className="font-semibold text-sm">{termDef.term}</p>
          <p className="text-sm font-normal">{definition}</p>
          {example && (
            <p className="text-xs italic text-muted-foreground">
              {example}
            </p>
          )}
          {termDef.formula && (
            <div className="mt-1">
              <button
                type="button"
                className="text-xs text-primary hover:underline"
                onClick={() => setShowFormula(!showFormula)}
              >
                {showFormula ? tg("hideFormula") : tg("seeFormula")}
              </button>
              {showFormula && (
                <pre className="mt-1 text-xs bg-muted/50 rounded px-2 py-1 font-mono">
                  {termDef.formula}
                </pre>
              )}
            </div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
