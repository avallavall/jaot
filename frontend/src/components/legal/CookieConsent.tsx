"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { getConsent, setConsent } from "@/lib/cookie-consent";

export function CookieConsent() {
  const [visible, setVisible] = useState(false);
  const t = useTranslations("public");

  useEffect(() => {
    if (getConsent() === null) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- initializing from external state (cookie storage) is intentional
      setVisible(true);
    }

    const handleShow = () => setVisible(true);
    window.addEventListener("jaot:show-cookie-consent", handleShow);
    return () => {
      window.removeEventListener("jaot:show-cookie-consent", handleShow);
    };
  }, []);

  if (!visible) return null;

  const handleAcceptAll = () => {
    setConsent(true);
    setVisible(false);
  };

  const handleRejectNonEssential = () => {
    setConsent(false);
    setVisible(false);
  };

  return (
    <div className="fixed bottom-0 inset-x-0 z-50 p-4 bg-background border-t shadow-lg">
      <div className="max-w-4xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground text-center sm:text-left">
          {t.rich("cookie.message", {
            link: (chunks) => (
              <Link href="/privacy" className="underline hover:text-foreground">
                {chunks}
              </Link>
            ),
          })}
        </p>
        <div className="flex items-center gap-2 shrink-0">
          <Button variant="outline" size="sm" onClick={handleRejectNonEssential}>
            {t("cookie.rejectNonEssential")}
          </Button>
          <Button size="sm" onClick={handleAcceptAll}>
            {t("cookie.acceptAll")}
          </Button>
        </div>
      </div>
    </div>
  );
}
