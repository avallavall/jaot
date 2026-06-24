"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { TriggerForm } from "@/components/triggers/TriggerForm";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { ChevronLeft, Copy, CheckCircle } from "lucide-react";
import { toast } from "sonner";

export default function NewTriggerPage() {
  const router = useRouter();
  const { activeWorkspaceId } = useAuth();
  const t = useTranslations("triggers.new");
  const [secretState, setSecretState] = useState<{
    triggerId: string;
    secret: string;
  } | null>(null);
  const [copied, setCopied] = useState(false);

  const handleSuccess = (triggerId: string, triggerSecret: string) => {
    setSecretState({ triggerId, secret: triggerSecret });
  };

  const handleCopySecret = async () => {
    if (!secretState) return;
    try {
      await navigator.clipboard.writeText(secretState.secret);
      setCopied(true);
      toast.success(t("secretCopied"));
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(t("copyError"));
    }
  };

  const handleContinue = () => {
    if (secretState) {
      const href = activeWorkspaceId
        ? `/triggers/${secretState.triggerId}?workspace_id=${activeWorkspaceId}`
        : `/triggers/${secretState.triggerId}`;
      router.push(href);
    }
  };

  // If trigger was just created, show the secret reveal screen
  if (secretState) {
    return (
      <div className="container mx-auto px-4 py-8 max-w-2xl">
        <div className="border rounded-xl p-8 bg-card text-center">
          <CheckCircle className="w-12 h-12 text-green-500 mx-auto mb-4" />
          <h1 className="text-2xl font-bold mb-2">{t("created")}</h1>
          <p className="text-muted-foreground mb-6">
            {t("secretWarning")}
          </p>

          <div className="bg-muted border rounded-lg p-4 mb-6">
            <p className="text-xs text-muted-foreground mb-2 font-medium uppercase tracking-wide">
              {t("secretLabel")}
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 font-mono text-sm text-left break-all">
                {secretState.secret}
              </code>
              <Button
                variant="outline"
                size="sm"
                onClick={handleCopySecret}
                className="shrink-0"
              >
                {copied ? (
                  <CheckCircle className="w-4 h-4 text-green-500" />
                ) : (
                  <Copy className="w-4 h-4" />
                )}
              </Button>
            </div>
          </div>

          <div className="bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 rounded-lg p-4 mb-6 text-left">
            <p className="text-sm text-amber-800 dark:text-amber-300">
              {t.rich("importantNote", { strong: (chunks) => <strong>{chunks}</strong> })}
            </p>
          </div>

          <p className="text-sm text-muted-foreground mb-4">
            {t.rich("authUsage", { code: (chunks) => <code>{chunks}</code> })}
          </p>

          <Button onClick={handleContinue} className="w-full">
            {t("continueToDetails")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8 max-w-2xl">
      <div className="mb-6">
        <Link
          href="/triggers"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
          {t("backToTriggers")}
        </Link>
      </div>

      <div className="mb-8">
        <h1 className="text-3xl font-bold mb-2">{t("title")}</h1>
        <p className="text-muted-foreground">
          {t("subtitle")}
        </p>
      </div>

      <TriggerForm onSuccess={handleSuccess} workspaceId={activeWorkspaceId ?? undefined} />
    </div>
  );
}
