"use client";

import { useState, useCallback } from "react";
import { Dialog as DialogPrimitive } from "radix-ui";
import { useTranslations } from "next-intl";
import { useGuidance } from "@/contexts/GuidanceContext";
import { useAuth } from "@/contexts/AuthContext";
import { WizardStepContent } from "./WizardStepContent";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { SkillLevel } from "@/lib/types";

const TOTAL_STEPS = 4;

function StepIndicator({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex items-center justify-center gap-0">
      {Array.from({ length: total }, (_, i) => {
        const step = i + 1;
        const isActive = step === current;
        const isCompleted = step < current;
        return (
          <div key={step} className="flex items-center">
            <div
              className={cn(
                "flex h-8 w-8 items-center justify-center rounded-full text-sm font-medium transition-colors",
                isActive && "bg-primary text-primary-foreground",
                isCompleted && "bg-primary/20 text-primary",
                !isActive && !isCompleted && "bg-muted text-muted-foreground"
              )}
            >
              {step}
            </div>
            {step < total && (
              <div
                className={cn(
                  "h-0.5 w-8",
                  isCompleted ? "bg-primary/40" : "bg-muted"
                )}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

export function WelcomeWizard() {
  const { isAuthenticated } = useAuth();
  const {
    wizardStep,
    wizardDismissed,
    wizardCompleted,
    isLoading,
    skillLevel,
    setSkillLevel,
    advanceWizard,
    dismissWizard,
  } = useGuidance();
  const t = useTranslations("common");

  const [selectedSkill, setSelectedSkill] = useState<SkillLevel>(skillLevel);

  const isOpen =
    isAuthenticated &&
    !isLoading &&
    !wizardCompleted &&
    !wizardDismissed &&
    wizardStep >= 0 &&
    wizardStep < 5;

  // The effective display step: if wizardStep is 0 (not started), show step 1
  const displayStep = wizardStep === 0 ? 1 : wizardStep;

  const handleNext = useCallback(async () => {
    // On step 1, persist skill level before advancing
    if (displayStep === 1) {
      await setSkillLevel(selectedSkill);
    }
    await advanceWizard();
  }, [displayStep, selectedSkill, setSkillLevel, advanceWizard]);

  const handleSkip = useCallback(async () => {
    await dismissWizard();
  }, [dismissWizard]);

  const isLastStep = displayStep === TOTAL_STEPS;

  if (!isOpen) return null;

  return (
    <DialogPrimitive.Root open modal>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/50 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content
          onInteractOutside={(e) => e.preventDefault()}
          onEscapeKeyDown={(e) => e.preventDefault()}
          className="fixed top-[50%] left-[50%] z-50 w-full max-w-md translate-x-[-50%] translate-y-[-50%] rounded-lg border bg-background p-6 shadow-lg data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95"
        >
          <DialogPrimitive.Title className="sr-only">
            {t("guidance.wizardTitle")}
          </DialogPrimitive.Title>
          <DialogPrimitive.Description className="sr-only">
            {t("guidance.wizardDescription")}
          </DialogPrimitive.Description>

          <div className="mb-6">
            <StepIndicator current={displayStep} total={TOTAL_STEPS} />
          </div>

          <div className="min-h-[220px]">
            <WizardStepContent
              step={displayStep}
              selectedSkillLevel={selectedSkill}
              onSkillLevelChange={setSelectedSkill}
            />
          </div>

          <div className="mt-6 flex items-center justify-between">
            <button
              type="button"
              onClick={handleSkip}
              className="text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              {t("guidance.skipWizard")}
            </button>
            <div className="flex gap-2">
              {displayStep > 1 && (
                <Button variant="outline" size="sm" disabled>
                  {t("guidance.back")}
                </Button>
              )}
              <Button size="sm" onClick={handleNext}>
                {isLastStep ? t("guidance.finish") : t("next")}
              </Button>
            </div>
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
