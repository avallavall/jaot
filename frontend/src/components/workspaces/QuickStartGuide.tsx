"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { X, Lightbulb } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";

const STORAGE_KEY = "jaot_team_quickstart_dismissed";

export function QuickStartGuide() {
  const t = useTranslations("workspace.team.quickStart");
  const [dismissed, setDismissed] = useState(true);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDismissed(stored === "true");
  }, []);

  const handleDismiss = () => {
    setDismissed(true);
    localStorage.setItem(STORAGE_KEY, "true");
  };

  if (dismissed) return null;

  return (
    <div className="mb-6 border rounded-lg bg-card p-5 relative">
      <div className="flex items-start gap-3">
        <Lightbulb className="w-5 h-5 text-primary mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2 mb-3">
            <h2 className="text-base font-semibold">{t("title")}</h2>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleDismiss}
              className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground shrink-0"
              aria-label={t("dismiss")}
            >
              <X className="w-3.5 h-3.5 mr-1" />
              {t("dismiss")}
            </Button>
          </div>

          <Accordion type="multiple" className="w-full">
            <AccordionItem value="what-is">
              <AccordionTrigger className="text-sm py-3">
                {t("whatIs")}
              </AccordionTrigger>
              <AccordionContent className="text-sm text-muted-foreground">
                {t("whatIsDescription")}
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="invite">
              <AccordionTrigger className="text-sm py-3">
                {t("howToInvite")}
              </AccordionTrigger>
              <AccordionContent className="text-sm text-muted-foreground">
                {t("howToInviteDescription")}
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="roles">
              <AccordionTrigger className="text-sm py-3">
                {t("roles")}
              </AccordionTrigger>
              <AccordionContent className="text-sm text-muted-foreground">
                <p className="mb-2">{t("rolesDescription")}</p>
                <ul className="space-y-1.5 ml-1">
                  <li className="flex gap-2">
                    <span className="text-muted-foreground/60">--</span>
                    <span>{t("roleViewer")}</span>
                  </li>
                  <li className="flex gap-2">
                    <span className="text-muted-foreground/60">--</span>
                    <span>{t("roleSolver")}</span>
                  </li>
                  <li className="flex gap-2">
                    <span className="text-muted-foreground/60">--</span>
                    <span>{t("roleEditor")}</span>
                  </li>
                  <li className="flex gap-2">
                    <span className="text-muted-foreground/60">--</span>
                    <span>{t("roleAdmin")}</span>
                  </li>
                </ul>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="billing">
              <AccordionTrigger className="text-sm py-3">
                {t("billing")}
              </AccordionTrigger>
              <AccordionContent className="text-sm text-muted-foreground">
                {t("billingDescription")}
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        </div>
      </div>
    </div>
  );
}
