"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslations } from "next-intl";

/**
 * AI Assistant entry point.
 *
 * Creates a new builder document and redirects to its chat page.
 * This provides a clean sidebar entry without needing a pre-existing documentId.
 */
export default function AIAssistantRedirectPage() {
  const t = useTranslations("builder");
  const router = useRouter();
  const { activeWorkspaceId, isLoading, isAuthenticated } = useAuth();
  const [error, setError] = useState(false);

  useEffect(() => {
    if (isLoading || !isAuthenticated) return;

    const controller = new AbortController();

    async function createAndRedirect() {
      try {
        const doc = await api.createBuilderDocument(
          "AI-Generated Model",
          activeWorkspaceId ?? undefined,
          controller.signal,
        );
        router.replace(`/builder/${doc.id}/chat`);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;

        // Retry once for transient network errors (e.g. React Strict Mode remount)
        if (err instanceof TypeError && /fetch/i.test(err.message)) {
          await new Promise((r) => setTimeout(r, 500));
          if (controller.signal.aborted) return;
          try {
            const doc = await api.createBuilderDocument(
              "AI-Generated Model",
              activeWorkspaceId ?? undefined,
              controller.signal,
            );
            router.replace(`/builder/${doc.id}/chat`);
            return;
          } catch (retryErr) {
            if (retryErr instanceof DOMException && retryErr.name === "AbortError") return;
            // Fall through to error handling below
          }
        }

        console.error("Failed to create document for AI assistant:", err);
        toast.error(t("aiAssistant.startFailed"));
        setError(true);
      }
    }

    createAndRedirect();

    return () => {
      controller.abort();
    };
  }, [router, activeWorkspaceId, isLoading, isAuthenticated, t]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="space-y-3 w-64">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-3/4" />
          <p className="text-xs text-muted-foreground text-center">
            {t("aiAssistant.starting")}
          </p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center space-y-3">
          <p className="text-muted-foreground">{t("aiAssistant.initFailed")}</p>
          <button
            onClick={() => router.push("/builder")}
            className="text-sm text-primary underline"
          >
            {t("aiAssistant.goBack")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center h-full">
      <div className="space-y-3 w-64">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-3/4" />
        <p className="text-xs text-muted-foreground text-center">
          {t("aiAssistant.starting")}
        </p>
      </div>
    </div>
  );
}
