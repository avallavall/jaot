"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useGuidance } from "@/contexts/GuidanceContext";
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

export function WizardStepContent({
  step,
  selectedSkillLevel,
  onSkillLevelChange,
}: WizardStepContentProps) {
  const { skillLevel } = useGuidance();
  const t = useTranslations("common");
  const [problemText, setProblemText] = useState(EXAMPLE_PROBLEM);
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
          <textarea
            className="w-full min-h-[120px] rounded-lg border bg-background p-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
            value={problemText}
            onChange={(e) => setProblemText(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            {t("guidance.step2NextHint")}
          </p>
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
          <Link href="/builder/ai-assistant">
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
          <div className="grid grid-cols-2 gap-2">
            <Link href="/marketplace">
              <Button variant="outline" className="w-full justify-start" size="sm">
                {t("guidance.modelCatalog")}
              </Button>
            </Link>
            <Link href="/builder/new">
              <Button variant="outline" className="w-full justify-start" size="sm">
                {t("guidance.visualBuilder")}
              </Button>
            </Link>
            <Link href="/solve/executions">
              <Button variant="outline" className="w-full justify-start" size="sm">
                {t("guidance.executions")}
              </Button>
            </Link>
            <Link href="/workspace/credits">
              <Button variant="outline" className="w-full justify-start" size="sm">
                {t("guidance.credits")}
              </Button>
            </Link>
          </div>
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
