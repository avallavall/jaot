"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useGuidance } from "@/contexts/GuidanceContext";
import { useDslStatus } from "@/hooks/useDslStatus";
import { SkillLevelSelector } from "./SkillLevelSelector";
import { Button } from "@/components/ui/button";
import type { SkillLevel } from "@/lib/types";
import {
  BookOpen,
  ExternalLink,
  Lightbulb,
  MessageSquare,
  Play,
  Rocket,
  Bug,
} from "lucide-react";
import { fetchCommunityStatus, FEEDBACK_URL, type CommunityStatus } from "@/lib/community";

interface WizardStepContentProps {
  step: number;
  selectedSkillLevel: SkillLevel;
  onSkillLevelChange: (level: SkillLevel) => void;
}

const EXAMPLE_PROBLEM = `I have a backpack that holds 15 kg. I want to pack items to maximize total value: laptop (3kg, $500), camera (2kg, $300), book (1kg, $50), tent (5kg, $200), snacks (1kg, $30).`;

/**
 * The sidebar, as the wizard shows it — same routes, same `nav.*` labels, same
 * three groups (see components/layout/nav-items.tsx).
 *
 * Triggers is deliberately absent: a trigger's `document_id` is a NOT NULL
 * foreign key to `model_builder_documents`, and the studio never creates one, so
 * nothing built here can be automated yet. Sending a new account to it on its
 * first minute would be sending it to a dead end.
 */
const NAV_MAP = [
  {
    heading: "nav.modelAnalyzeSolve",
    entries: [
      { label: "nav.myModels", href: "/studio" },
      { label: "nav.newModel", href: "/studio/new" },
      { label: "nav.templates", href: "/studio/templates" },
    ],
  },
  {
    heading: "nav.discover",
    entries: [
      { label: "nav.marketplace", href: "/marketplace" },
      { label: "nav.favorites", href: "/solve/favorites" },
    ],
  },
  {
    heading: "nav.activity",
    entries: [
      { label: "nav.executions", href: "/solve/executions" },
      { label: "nav.solveAnalytics", href: "/solve/analytics" },
    ],
  },
] as const;

export function WizardStepContent({
  step,
  selectedSkillLevel,
  onSkillLevelChange,
}: WizardStepContentProps) {
  const { skillLevel } = useGuidance();
  const t = useTranslations("common");
  // The launcher's own labels and the sidebar's own labels, not copies of them:
  // a wizard that paraphrases the product drifts from it the first time either
  // is renamed. Steps 3 and 4 below read the same strings those surfaces read.
  const tStudio = useTranslations("studio");
  const dslEnabled = useDslStatus();
  const [communityStatus, setCommunityStatus] = useState<CommunityStatus | null>(null);

  useEffect(() => {
    if (step === 4) {
      fetchCommunityStatus().then(setCommunityStatus);
    }
  }, [step]);

  const verbose = skillLevel === "beginner";
  const brief = skillLevel === "intermediate";

  switch (step) {
    case 1:
      return (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-primary">
            <Lightbulb className="h-5 w-5" />
            <h2 className="text-xl font-semibold">{t("guidance.welcomeTitle")}</h2>
          </div>
          {verbose && (
            <p className="text-sm text-muted-foreground">
              {t("guidance.step1Verbose")}
            </p>
          )}
          {brief && (
            <p className="text-sm text-muted-foreground">
              {t("guidance.step1Brief")}
            </p>
          )}
          {!verbose && !brief && (
            <p className="text-sm text-muted-foreground">
              {t("guidance.step1Expert")}
            </p>
          )}
          <SkillLevelSelector
            value={selectedSkillLevel}
            onChange={onSkillLevelChange}
          />
        </div>
      );

    case 2:
      return (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-primary">
            <BookOpen className="h-5 w-5" />
            <h2 className="text-xl font-semibold">{t("guidance.step2Title")}</h2>
          </div>
          {verbose && (
            <p className="text-sm text-muted-foreground">
              {t("guidance.step2Verbose")}
            </p>
          )}
          {brief && (
            <p className="text-sm text-muted-foreground">
              {t("guidance.step2Brief")}
            </p>
          )}
          {!verbose && !brief && (
            <p className="text-sm text-muted-foreground">
              {t("guidance.step2Expert")}
            </p>
          )}
          {/* Shown, not asked for. This used to be an editable textarea whose
              contents nothing ever read: the next step then told the reader
              "the AI assistant has turned your words into a mathematical
              model", which had not happened and could not have. An example of
              what the assistant formulates keeps the teaching and drops the
              claim. */}
          <pre className="w-full whitespace-pre-wrap rounded-lg border bg-muted/40 p-3 text-sm text-muted-foreground">
            {EXAMPLE_PROBLEM}
          </pre>
        </div>
      );

    case 3:
      return (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-primary">
            <Play className="h-5 w-5" />
            <h2 className="text-xl font-semibold">{t("guidance.step3Title")}</h2>
          </div>
          {verbose && (
            <p className="text-sm text-muted-foreground">
              {t("guidance.step3Verbose")}
            </p>
          )}
          {brief && (
            <p className="text-sm text-muted-foreground">
              {t("guidance.step3Brief")}
            </p>
          )}
          {!verbose && !brief && (
            <p className="text-sm text-muted-foreground">
              {t("guidance.step3Expert")}
            </p>
          )}
          {/* Every way into a model, named exactly as the launcher names them.
              JModel is hidden here when it is hidden there — JAOT_DSL ships off,
              and a wizard that promises a tab the reader cannot see is worse
              than one that stays quiet about it. */}
          <ul className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm text-muted-foreground">
            {[
              tStudio("tileAi"),
              tStudio("tileVisual"),
              tStudio("tileEditor"),
              ...(dslEnabled ? [tStudio("tileJModel")] : []),
              tStudio("tileImport"),
              tStudio("tileTemplate"),
              tStudio("tileMarketplace"),
              tStudio("tileBlank"),
            ].map((label) => (
              <li key={label} className="flex items-center gap-2">
                <span aria-hidden className="h-1 w-1 shrink-0 rounded-full bg-primary/60" />
                {label}
              </li>
            ))}
          </ul>
          {/* The launcher, not /builder/ai-assistant: the studio is the one door
              (see components/layout/nav-items.tsx), and /builder was taken out of
              the menu — so the very first screen a new account sees was pushing
              it straight back into the retired area. */}
          <Link href="/studio/new">
            <Button className="w-full">{t("guidance.openAiAssistant")}</Button>
          </Link>
        </div>
      );

    case 4:
      return (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-primary">
            <Rocket className="h-5 w-5" />
            <h2 className="text-xl font-semibold">{t("guidance.step4Title")}</h2>
          </div>
          {verbose && (
            <p className="text-sm text-muted-foreground">
              {t("guidance.step4Verbose")}
            </p>
          )}
          {brief && (
            <p className="text-sm text-muted-foreground">
              {t("guidance.step4Brief")}
            </p>
          )}
          {!verbose && !brief && (
            <p className="text-sm text-muted-foreground">{t("guidance.step4Expert")}</p>
          )}
          {/* The sidebar's three groups, its routes and its labels. It used to be
              three fixed buttons — catalog, "Visual Builder" (into the retired
              /builder), executions — which named neither the studio nor half the
              product. Reading `nav.*` here means the map a new account is handed
              on its first minute cannot drift from the menu it will use next. */}
          {NAV_MAP.map((group) => (
            <div key={group.heading} className="space-y-2">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {t(group.heading)}
              </p>
              <div className="grid grid-cols-2 gap-2">
                {group.entries.map((entry) => (
                  <Link key={entry.href} href={entry.href}>
                    <Button variant="outline" className="w-full justify-start" size="sm">
                      {t(entry.label)}
                    </Button>
                  </Link>
                ))}
              </div>
            </div>
          ))}
          <div className="grid grid-cols-2 gap-2 mt-2">
            {communityStatus?.discourse_enabled && (
              <a
                href={`${communityStatus.discourse_url}/session/sso`}
                target="_blank"
                rel="noopener noreferrer"
              >
                <Button variant="outline" className="w-full justify-start gap-2" size="sm">
                  <MessageSquare className="w-3.5 h-3.5" />
                  {t("guidance.communityForum")}
                  <ExternalLink className="w-3 h-3 ml-auto text-muted-foreground" />
                </Button>
              </a>
            )}
            <a
              href={FEEDBACK_URL}
              target="_blank"
              rel="noopener noreferrer"
            >
              <Button variant="outline" className="w-full justify-start gap-2" size="sm">
                <Bug className="w-3.5 h-3.5" />
                {t("guidance.feedbackAndBugs")}
                <ExternalLink className="w-3 h-3 ml-auto text-muted-foreground" />
              </Button>
            </a>
          </div>
        </div>
      );

    default:
      return null;
  }
}
