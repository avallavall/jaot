"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { X } from "lucide-react";

interface HomeAnnouncementBannerClientProps {
  messages: string[];
  rotationSeconds: number;
}

const STORAGE_PREFIX = "jaot.banner.dismissed.";

export function HomeAnnouncementBannerClient({
  messages,
  rotationSeconds,
}: HomeAnnouncementBannerClientProps) {
  const t = useTranslations("public.announcement");
  // The joined message string is itself a unique key — admin edits naturally
  // invalidate a stale dismissal without needing any hash.
  const storageKey = useMemo(() => STORAGE_PREFIX + messages.join("|"), [messages]);
  const [dismissed, setDismissed] = useState(false);
  const [index, setIndex] = useState(0);

  // Honor a previous dismissal once mounted. We start with dismissed=false to
  // avoid an SSR/CSR mismatch — the brief flash of the banner is acceptable
  // and only happens for users who dismissed it before. The set-state-in-effect
  // rule is intentionally disabled here: hydrating client-only state
  // (localStorage) is one of the legitimate uses of useEffect post-SSR.
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      if (window.localStorage.getItem(storageKey) === "1") {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setDismissed(true);
      }
    } catch {
      // ignore storage errors (private mode, quota exceeded, etc.)
    }
  }, [storageKey]);

  // Rotate through messages when more than one exists. The interval is
  // capped server-side by the registry (min=2, max=60) so we trust the value.
  useEffect(() => {
    if (messages.length <= 1) return;
    const id = window.setInterval(() => {
      setIndex((i) => (i + 1) % messages.length);
    }, rotationSeconds * 1000);
    return () => window.clearInterval(id);
  }, [messages.length, rotationSeconds]);

  if (dismissed) return null;

  const handleDismiss = () => {
    setDismissed(true);
    try {
      window.localStorage.setItem(storageKey, "1");
    } catch {
      // ignore storage errors
    }
  };

  const current = messages[index] ?? messages[0];

  return (
    <div
      role="region"
      aria-label={t("regionLabel")}
      className="relative w-full bg-red-600 text-black"
    >
      <div className="max-w-6xl mx-auto px-6 py-2 flex items-center justify-center gap-3">
        <p
          key={index}
          className="text-sm font-medium text-center transition-opacity duration-300"
          aria-live="polite"
        >
          {current}
        </p>
        <button
          type="button"
          onClick={handleDismiss}
          aria-label={t("dismiss")}
          className="absolute right-3 top-1/2 -translate-y-1/2 inline-flex h-6 w-6 items-center justify-center rounded hover:bg-red-700/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
