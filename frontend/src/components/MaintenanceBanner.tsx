"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { MAINTENANCE_PAGE_ATTRIBUTE } from "@/lib/maintenance";

/**
 * Full-screen maintenance overlay that activates when the API returns
 * a 503 with `{ status: "maintenance" }`.
 *
 * Listens for the `jaot:maintenance` custom event dispatched by the
 * API client in `lib/api.ts`.
 */
export function MaintenanceBanner() {
  const t = useTranslations("maintenance");
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    function handleMaintenance() {
      // The maintenance page makes API calls too, and they answer 503. The
      // overlay then drew the same notice over the page, so the text was on
      // screen and in the DOM twice. The page already says it.
      if (document.querySelector(`[${MAINTENANCE_PAGE_ATTRIBUTE}]`)) return;
      setVisible(true);
    }

    window.addEventListener("jaot:maintenance", handleMaintenance);
    return () => {
      window.removeEventListener("jaot:maintenance", handleMaintenance);
    };
  }, []);

  if (!visible) return null;

  // The server's 503 carries an English sentence. The same words exist in
  // every locale under `maintenance.message`, so the overlay uses those.
  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-background/95 backdrop-blur-sm">
      <div className="mx-4 max-w-md rounded-lg border bg-card p-8 text-center shadow-lg">
        <div className="mb-4 text-4xl">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="mx-auto h-12 w-12 text-muted-foreground"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M11.42 15.17 17.25 21A2.652 2.652 0 0 0 21 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 1 1-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 0 0 4.486-6.336l-3.276 3.277a3.004 3.004 0 0 1-2.25-2.25l3.276-3.276a4.5 4.5 0 0 0-6.336 4.486c.049.58.025 1.192-.14 1.743"
            />
          </svg>
        </div>
        <h2 className="mb-2 text-xl font-semibold text-foreground">
          {t("heading")}
        </h2>
        <p className="mb-6 text-muted-foreground">{t("message")}</p>
        <button
          onClick={() => window.location.reload()}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
        >
          {t("retry")}
        </button>
      </div>
    </div>
  );
}
