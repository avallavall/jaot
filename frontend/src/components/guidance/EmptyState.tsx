"use client";

import Link from "next/link";
import { useMemo } from "react";
import { Button } from "@/components/ui/button";
import { useGuidance } from "@/contexts/GuidanceContext";
import type { SkillLevel } from "@/lib/types";

/** Per-skill-level CTA override. */
export interface SkillLevelCTA {
  actionLabel: string;
  actionHref?: string;
  onAction?: () => void;
  secondaryActions?: { label: string; href: string }[];
}

interface EmptyStateProps {
  icon: React.ReactNode;
  title: string;
  description: string;
  expertDescription?: string;
  /** Default primary CTA (used when no skill-level override matches). */
  actionLabel: string;
  actionHref?: string;
  onAction?: () => void;
  secondaryActionLabel?: string;
  secondaryActionHref?: string;
  /**
   * Optional skill-level-specific CTA overrides.
   * When provided, the matching skill level entry replaces the default
   * primary + secondary CTAs.
   */
  skillLevelCTAs?: Partial<Record<SkillLevel, SkillLevelCTA>>;
}

/**
 * Reusable empty-state component with skill-level adaptation.
 *
 * When the user's skill level is "expert" and an `expertDescription` is
 * provided, the shorter text is displayed instead of the full description.
 *
 * When `skillLevelCTAs` is provided, the primary and secondary CTAs adapt
 * based on the user's skill level:
 *   - Beginner: "Browse Templates" primary, "Create with AI" secondary
 *   - Intermediate: "Create with AI" primary, "Browse Templates" + "Blank Canvas" secondary
 *   - Expert: "Blank Canvas" primary, "Create with AI" secondary
 *
 * All guidance is non-blocking (GUIDE-06) -- this component is purely
 * informational with optional CTAs.
 */
export function EmptyState({
  icon,
  title,
  description,
  expertDescription,
  actionLabel,
  actionHref,
  onAction,
  secondaryActionLabel,
  secondaryActionHref,
  skillLevelCTAs,
}: EmptyStateProps) {
  const { skillLevel } = useGuidance();

  const displayDescription =
    skillLevel === "expert" && expertDescription
      ? expertDescription
      : description;

  // Resolve CTAs based on skill level overrides or fall back to defaults.
  const resolved = useMemo(() => {
    const override = skillLevelCTAs?.[skillLevel];
    if (override) {
      return {
        primaryLabel: override.actionLabel,
        primaryHref: override.actionHref,
        primaryOnAction: override.onAction,
        secondaryActions: override.secondaryActions ?? [],
      };
    }
    const fallbackSecondary =
      secondaryActionLabel && secondaryActionHref
        ? [{ label: secondaryActionLabel, href: secondaryActionHref }]
        : [];
    return {
      primaryLabel: actionLabel,
      primaryHref: actionHref,
      primaryOnAction: onAction,
      secondaryActions: fallbackSecondary,
    };
  }, [
    skillLevel,
    skillLevelCTAs,
    actionLabel,
    actionHref,
    onAction,
    secondaryActionLabel,
    secondaryActionHref,
  ]);

  const primaryButton = (
    <Button onClick={resolved.primaryOnAction}>{resolved.primaryLabel}</Button>
  );

  return (
    <div className="border-2 border-dashed rounded-xl p-12 text-center">
      <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center text-muted-foreground/40">
        {icon}
      </div>

      <h3 className="font-medium text-lg mb-1">{title}</h3>

      <p className="text-muted-foreground text-sm mb-4">{displayDescription}</p>

      {resolved.primaryHref ? (
        <Link href={resolved.primaryHref}>{primaryButton}</Link>
      ) : (
        primaryButton
      )}

      {resolved.secondaryActions.length > 0 && (
        <div className="mt-3 flex items-center justify-center gap-4">
          {resolved.secondaryActions.map((action) => (
            <Link
              key={action.href}
              href={action.href}
              className="text-sm text-muted-foreground hover:text-foreground underline-offset-4 hover:underline"
            >
              {action.label}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
