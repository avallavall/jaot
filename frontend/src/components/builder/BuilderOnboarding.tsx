"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/button";
import { useTranslations } from "next-intl";
import { useGuidance } from "@/contexts/GuidanceContext";

const STORAGE_KEY = "builder_onboarding_complete";

interface OnboardingStep {
  readonly targetSelector: string;
  readonly titleKey: string;
  readonly descriptionKey: string;
}

const STEPS: readonly OnboardingStep[] = [
  {
    targetSelector: "[data-onboarding-target='objective']",
    titleKey: "step1Title",
    descriptionKey: "step1Description",
  },
  {
    targetSelector: "[data-onboarding-target='palette']",
    titleKey: "step2Title",
    descriptionKey: "step2Description",
  },
  {
    targetSelector: "[data-onboarding-target='canvas']",
    titleKey: "step3Title",
    descriptionKey: "step3Description",
  },
  {
    targetSelector: "[data-onboarding-target='solve']",
    titleKey: "step4Title",
    descriptionKey: "step4Description",
  },
] as const;

interface SpotlightRect {
  readonly top: number;
  readonly left: number;
  readonly width: number;
  readonly height: number;
}

type TooltipPosition = "bottom" | "right" | "top" | "left";

function getTooltipPosition(rect: SpotlightRect, viewportWidth: number, viewportHeight: number): TooltipPosition {
  const spaceBelow = viewportHeight - (rect.top + rect.height);
  const spaceRight = viewportWidth - (rect.left + rect.width);
  const spaceAbove = rect.top;
  const spaceLeft = rect.left;

  // Prefer bottom, then right, then top, then left
  if (spaceBelow >= 220) return "bottom";
  if (spaceRight >= 340) return "right";
  if (spaceAbove >= 220) return "top";
  if (spaceLeft >= 340) return "left";
  return "bottom";
}

function getTooltipStyle(
  rect: SpotlightRect,
  position: TooltipPosition,
): React.CSSProperties {
  const gap = 12;
  switch (position) {
    case "bottom":
      return {
        top: rect.top + rect.height + gap,
        left: rect.left + rect.width / 2,
        transform: "translateX(-50%)",
      };
    case "top":
      return {
        bottom: window.innerHeight - rect.top + gap,
        left: rect.left + rect.width / 2,
        transform: "translateX(-50%)",
      };
    case "right":
      return {
        top: rect.top + rect.height / 2,
        left: rect.left + rect.width + gap,
        transform: "translateY(-50%)",
      };
    case "left":
      return {
        top: rect.top + rect.height / 2,
        right: window.innerWidth - rect.left + gap,
        transform: "translateY(-50%)",
      };
  }
}

export function useBuilderOnboarding() {
  const [isVisible, setIsVisible] = useState(false);
  const [instanceKey, setInstanceKey] = useState(0);
  const { wizardDismissed, wizardCompleted, isLoading: guidanceLoading, dismissWizard: dismissGuidance } = useGuidance();

  useEffect(() => {
    // Wait for guidance state to load from backend before deciding
    if (guidanceLoading) return;

    // Skip if dismissed/completed via backend (persists across devices)
    if (wizardDismissed || wizardCompleted) return;

    try {
      const completed = localStorage.getItem(STORAGE_KEY);
      if (!completed) {
        // Small delay to let the builder canvas render first
        const timer = setTimeout(() => setIsVisible(true), 800);
        return () => clearTimeout(timer);
      }
    } catch {
      // localStorage not available
    }
  }, [guidanceLoading, wizardDismissed, wizardCompleted]);

  const restart = useCallback(() => {
    // Increment key to re-mount component with fresh state (resets step to 0)
    setInstanceKey((k) => k + 1);
    setIsVisible(true);
  }, []);

  const dismiss = useCallback(() => {
    setIsVisible(false);
    try {
      localStorage.setItem(STORAGE_KEY, "true");
    } catch {
      // localStorage not available
    }
    // Also persist to backend so it stays dismissed across devices
    dismissGuidance();
  }, [dismissGuidance]);

  return { isVisible, instanceKey, restart, dismiss };
}

interface BuilderOnboardingProps {
  readonly isVisible: boolean;
  readonly onDismiss: () => void;
}

export function BuilderOnboarding({ isVisible, onDismiss }: BuilderOnboardingProps) {
  const t = useTranslations("builder.onboarding");
  const [currentStep, setCurrentStep] = useState(0);
  const [spotlightRect, setSpotlightRect] = useState<SpotlightRect | null>(null);
  const overlayRef = useRef<HTMLDivElement>(null);

  // Measure spotlight target position via rAF (deferred, not synchronous in effect)
  useEffect(() => {
    if (!isVisible) return;

    let rafId: number;
    const measure = () => {
      const step = STEPS[currentStep];
      if (!step) return;

      const target = document.querySelector(step.targetSelector);
      if (target) {
        const rect = target.getBoundingClientRect();
        const padding = 8;
        setSpotlightRect({
          top: rect.top - padding,
          left: rect.left - padding,
          width: rect.width + padding * 2,
          height: rect.height + padding * 2,
        });
      } else {
        setSpotlightRect(null);
      }
    };

    // Defer initial measurement to next animation frame
    rafId = requestAnimationFrame(measure);

    const handleResize = () => {
      cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(measure);
    };
    window.addEventListener("resize", handleResize);

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener("resize", handleResize);
    };
  }, [isVisible, currentStep]);

  const handleNext = useCallback(() => {
    if (currentStep < STEPS.length - 1) {
      setCurrentStep((prev) => prev + 1);
    } else {
      onDismiss();
    }
  }, [currentStep, onDismiss]);

  const handlePrevious = useCallback(() => {
    if (currentStep > 0) {
      setCurrentStep((prev) => prev - 1);
    }
  }, [currentStep]);

  const handleSkip = useCallback(() => {
    onDismiss();
  }, [onDismiss]);

  if (!isVisible) return null;

  const step = STEPS[currentStep];
  if (!step) return null;

  const tooltipPosition = spotlightRect
    ? getTooltipPosition(spotlightRect, window.innerWidth, window.innerHeight)
    : "bottom";

  const tooltipStyle = spotlightRect
    ? getTooltipStyle(spotlightRect, tooltipPosition)
    : { top: "50%", left: "50%", transform: "translate(-50%, -50%)" };

  const overlayContent = (
    <div
      ref={overlayRef}
      className="fixed inset-0"
      style={{ zIndex: 9999 }}
      aria-modal="true"
      role="dialog"
      aria-label={t("ariaLabel")}
    >
      {/* Semi-transparent backdrop with spotlight cutout via SVG */}
      <svg
        className="absolute inset-0 w-full h-full"
        style={{ pointerEvents: "none" }}
      >
        <defs>
          <mask id="onboarding-spotlight-mask">
            <rect x="0" y="0" width="100%" height="100%" fill="white" />
            {spotlightRect && (
              <rect
                x={spotlightRect.left}
                y={spotlightRect.top}
                width={spotlightRect.width}
                height={spotlightRect.height}
                rx="8"
                ry="8"
                fill="black"
              />
            )}
          </mask>
        </defs>
        <rect
          x="0"
          y="0"
          width="100%"
          height="100%"
          fill="rgba(0,0,0,0.6)"
          mask="url(#onboarding-spotlight-mask)"
        />
      </svg>

      {spotlightRect && (
        <div
          className="absolute rounded-lg ring-2 ring-primary ring-offset-2 ring-offset-transparent"
          style={{
            top: spotlightRect.top,
            left: spotlightRect.left,
            width: spotlightRect.width,
            height: spotlightRect.height,
            pointerEvents: "none",
          }}
        />
      )}

      {/* Click-blocker overlay (invisible, captures clicks outside tooltip) */}
      <div
        className="absolute inset-0"
        onClick={handleSkip}
        style={{ cursor: "default" }}
      />

      <div
        className="absolute w-80 bg-popover text-popover-foreground border rounded-xl shadow-lg p-5"
        style={{ ...tooltipStyle, pointerEvents: "auto" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-1.5 mb-3">
          {STEPS.map((_, index) => (
            <div
              key={index}
              className={`h-1.5 rounded-full transition-all duration-300 ${
                index === currentStep
                  ? "w-6 bg-primary"
                  : index < currentStep
                    ? "w-3 bg-primary/40"
                    : "w-3 bg-muted-foreground/20"
              }`}
            />
          ))}
          <span className="ml-auto text-xs text-muted-foreground">
            {currentStep + 1}/{STEPS.length}
          </span>
        </div>

        <h3 className="text-sm font-semibold mb-1.5">
          {t(step.titleKey)}
        </h3>
        <p className="text-sm text-muted-foreground leading-relaxed mb-4">
          {t(step.descriptionKey)}
        </p>

        <div className="flex items-center justify-between">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleSkip}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            {t("skip")}
          </Button>
          <div className="flex gap-2">
            {currentStep > 0 && (
              <Button
                variant="outline"
                size="sm"
                onClick={handlePrevious}
                className="text-xs"
              >
                {t("previous")}
              </Button>
            )}
            <Button
              size="sm"
              onClick={handleNext}
              className="text-xs"
            >
              {currentStep === STEPS.length - 1 ? t("finish") : t("next")}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );

  return createPortal(overlayContent, document.body);
}
