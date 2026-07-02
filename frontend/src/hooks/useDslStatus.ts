"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

/**
 * One-time probe of whether the JModel DSL feature is enabled on this instance
 * (GET /api/v2/dsl/status). The flag is instance-wide, so a single fetch on mount is
 * enough. Cosmetic gating only — the real enforcement is the backend compile endpoint
 * returning 404 when the flag is off, so a brief `false` before the probe resolves is
 * harmless.
 */
export function useDslStatus(): boolean {
  const [enabled, setEnabled] = useState(false);
  useEffect(() => {
    let cancelled = false;
    api
      .dslStatus()
      .then((r) => {
        if (!cancelled) setEnabled(r.enabled);
      })
      .catch(() => {
        /* probe failure → treat as disabled; the compile endpoint still guards */
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return enabled;
}
