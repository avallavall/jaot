"use client";

import * as React from "react";
import { HelpCircle } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface HelpTooltipProps {
  /** The tooltip text content */
  content: string;
  /** Which side to show the tooltip on */
  side?: "top" | "bottom" | "left" | "right";
  /** Icon size in pixels */
  size?: number;
  /** Additional CSS classes for the trigger button */
  className?: string;
}

/**
 * A small "?" help icon with a Radix Tooltip that explains a concept.
 *
 * Self-contained: wraps its own TooltipProvider so it can be dropped
 * anywhere without requiring an ancestor provider.
 */
export function HelpTooltip({
  content,
  side = "top",
  size = 14,
  className = "",
}: HelpTooltipProps) {
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className={`inline-flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors cursor-help ${className}`}
            aria-label={content}
          >
            <HelpCircle size={size} />
          </button>
        </TooltipTrigger>
        <TooltipContent side={side} className="max-w-xs text-sm">
          {content}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
