"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import type { SkillLevel } from "@/lib/types";
import { api } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

interface GuidanceContextValue {
  skillLevel: SkillLevel;
  wizardStep: number;
  wizardDismissed: boolean;
  wizardCompleted: boolean;
  isLoading: boolean;
  setSkillLevel: (level: SkillLevel) => Promise<void>;
  /** Move to `target`, or one past the stored step when the caller has none. */
  advanceWizard: (target?: number) => Promise<void>;
  dismissWizard: () => Promise<void>;
  restartWizard: () => Promise<void>;
}

const DEFAULTS: GuidanceContextValue = {
  skillLevel: "beginner",
  wizardStep: 0,
  wizardDismissed: false,
  wizardCompleted: false,
  isLoading: false,
  setSkillLevel: async () => {},
  advanceWizard: async () => {},
  dismissWizard: async () => {},
  restartWizard: async () => {},
};

const GuidanceContext = createContext<GuidanceContextValue | null>(null);

export function GuidanceProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();

  const [skillLevel, setSkillLevelState] = useState<SkillLevel>("beginner");
  const [wizardStep, setWizardStep] = useState(0);
  const [wizardDismissed, setWizardDismissed] = useState(false);
  const [wizardCompleted, setWizardCompleted] = useState(false);
  const [isLoading, setIsLoading] = useState(isAuthenticated);

  useEffect(() => {
    if (!isAuthenticated) return;

    // eslint-disable-next-line react-hooks/set-state-in-effect
    setIsLoading(true);

    let cancelled = false;

    api
      .getGuidance()
      .then((state) => {
        if (cancelled) return;
        setSkillLevelState(state.skill_level);
        setWizardStep(state.wizard_step);
        setWizardDismissed(state.wizard_dismissed);
        setWizardCompleted(state.wizard_completed);
      })
      .catch(() => { /* keep defaults on error */ })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [isAuthenticated]);

  const setSkillLevel = useCallback(
    async (level: SkillLevel) => {
      setSkillLevelState(level); // optimistic
      try {
        const updated = await api.updateGuidance({ skill_level: level });
        setSkillLevelState(updated.skill_level);
        setWizardStep(updated.wizard_step);
        setWizardDismissed(updated.wizard_dismissed);
        setWizardCompleted(updated.wizard_completed);
      } catch {
        // Revert on failure by re-fetching; give up if that also fails.
        try {
          const current = await api.getGuidance();
          setSkillLevelState(current.skill_level);
        } catch { /* give up */ }
      }
    },
    [],
  );

  // `target` exists because the stored step and the displayed step are not the
  // same number: a fresh account is stored at 0 and shown step 1, so `+1` landed
  // back on step 1 and the first "Next" changed nothing on screen. Callers that
  // know which step the reader is looking at pass the one after it.
  const advanceWizard = useCallback(async (target?: number) => {
    const nextStep = Math.min(target ?? wizardStep + 1, 5);
    const completed = nextStep >= 5;
    setWizardStep(nextStep);
    if (completed) setWizardCompleted(true);
    try {
      const updated = await api.updateGuidance({
        wizard_step: nextStep,
        wizard_completed: completed || undefined,
      });
      setWizardStep(updated.wizard_step);
      setWizardCompleted(updated.wizard_completed);
    } catch { /* keep optimistic value */ }
  }, [wizardStep]);

  const dismissWizard = useCallback(async () => {
    setWizardDismissed(true);
    try {
      const updated = await api.updateGuidance({ wizard_dismissed: true });
      setWizardDismissed(updated.wizard_dismissed);
    } catch { /* keep optimistic value */ }
  }, []);

  const restartWizard = useCallback(async () => {
    setWizardStep(1);
    setWizardDismissed(false);
    setWizardCompleted(false);
    try {
      const updated = await api.updateGuidance({
        wizard_step: 1,
        wizard_dismissed: false,
        wizard_completed: false,
      });
      setWizardStep(updated.wizard_step);
      setWizardDismissed(updated.wizard_dismissed);
      setWizardCompleted(updated.wizard_completed);
    } catch { /* keep optimistic value */ }
  }, []);

  const value = useMemo<GuidanceContextValue>(
    () => ({
      skillLevel,
      wizardStep,
      wizardDismissed,
      wizardCompleted,
      isLoading,
      setSkillLevel,
      advanceWizard,
      dismissWizard,
      restartWizard,
    }),
    [
      skillLevel,
      wizardStep,
      wizardDismissed,
      wizardCompleted,
      isLoading,
      setSkillLevel,
      advanceWizard,
      dismissWizard,
      restartWizard,
    ],
  );

  return (
    <GuidanceContext.Provider value={value}>
      {children}
    </GuidanceContext.Provider>
  );
}

/** Safe outside provider — returns defaults. */
export function useGuidance(): GuidanceContextValue {
  const ctx = useContext(GuidanceContext);
  if (!ctx) return DEFAULTS;
  return ctx;
}
