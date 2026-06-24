"use client";

import { AuthProvider } from "@/contexts/AuthContext";
import { GuidanceProvider } from "@/contexts/GuidanceContext";
import { ThemeProvider } from "@/components/theme/ThemeProvider";
import { WelcomeWizard } from "@/components/guidance/WelcomeWizard";
import { TooltipSingletonProvider } from "@/components/ui/concept-tooltip";
import { MaintenanceBanner } from "@/components/MaintenanceBanner";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <AuthProvider>
        <GuidanceProvider>
          <WelcomeWizard />
          <MaintenanceBanner />
          <TooltipSingletonProvider>{children}</TooltipSingletonProvider>
        </GuidanceProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}
