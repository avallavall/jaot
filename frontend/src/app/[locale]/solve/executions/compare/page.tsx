"use client";

import { useState, useEffect, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { ModelExecution } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { useTranslations } from "next-intl";
import { ExecutionComparisonView } from "@/components/solve/ExecutionComparisonView";

// ──────────────────────────────────────────────────────────────
// Inner component (uses useSearchParams — must be inside Suspense)
// ──────────────────────────────────────────────────────────────

function ComparePageInner() {
  const t = useTranslations("solve.compare");
  const searchParams = useSearchParams();
  const router = useRouter();

  const idA = searchParams.get("a") ?? "";
  const idB = searchParams.get("b") ?? "";

  const [execA, setExecA] = useState<ModelExecution | null>(null);
  const [execB, setExecB] = useState<ModelExecution | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!idA || !idB) {
      setError(t("twoIdsRequired"));
      setLoading(false);
      return;
    }

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const [a, b] = await Promise.all([api.getExecution(idA), api.getExecution(idB)]);
        setExecA(a);
        setExecB(b);
      } catch (err) {
        setError(err instanceof Error ? err.message : t("failedToLoad"));
      } finally {
        setLoading(false);
      }
    };

    load();
  }, [idA, idB, t]);

  // ── Loading skeleton ──
  if (loading) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="animate-pulse space-y-4">
          <div className="h-6 bg-muted rounded w-1/4" />
          <div className="h-4 bg-muted rounded w-1/3" />
          <div className="grid grid-cols-2 gap-6 mt-6">
            <div className="h-48 bg-muted rounded" />
            <div className="h-48 bg-muted rounded" />
          </div>
          <div className="h-64 bg-muted rounded" />
        </div>
      </div>
    );
  }

  // ── Error state ──
  if (error || !execA || !execB) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-6 text-center">
          <p className="text-destructive mb-4">{error ?? t("executionNotFound")}</p>
          <Button variant="outline" onClick={() => router.back()}>
            {t("goBack")}
          </Button>
        </div>
      </div>
    );
  }

  // ── No result data guard ──
  if (!execA.result_data || !execB.result_data) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="bg-muted border border-border rounded-lg p-6 text-center">
          <p className="text-muted-foreground mb-4">
            {t("cannotCompare")}
          </p>
          <Button variant="outline" onClick={() => router.back()}>
            {t("goBack")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="mb-6">
        <button
          onClick={() => router.back()}
          className="text-sm text-muted-foreground hover:text-foreground mb-2 inline-block"
        >
          {t("back")}
        </button>
        <h1 className="text-2xl font-bold text-foreground">{t("title")}</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Comparing{" "}
          <span className="font-mono text-xs bg-muted px-1.5 py-0.5 rounded">{idA}</span>
          {" "}vs{" "}
          <span className="font-mono text-xs bg-muted px-1.5 py-0.5 rounded">{idB}</span>
        </p>
      </div>

      <ExecutionComparisonView executionA={execA} executionB={execB} />
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Page export — wrapped in Suspense (required for useSearchParams)
// ──────────────────────────────────────────────────────────────

export default function ComparisonPage() {
  return (
    <Suspense
      fallback={
        <div className="container mx-auto px-4 py-8">
          <div className="animate-pulse space-y-4">
            <div className="h-6 bg-muted rounded w-1/4" />
            <div className="h-64 bg-muted rounded" />
          </div>
        </div>
      }
    >
      <ComparePageInner />
    </Suspense>
  );
}
