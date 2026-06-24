"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";

export interface SolverInfo {
  name: string;
  available: boolean;
  description?: string;
  /** Credit multiplier badge. */
  multiplier?: number;
  /** Present when available=false. */
  reason?: string;
  /** Seconds until re-check. */
  retry_after?: number | null;
}

// "auto" is the server-side routed pseudo-solver — backend picks the effective solver per problem.
const DEFAULT_SOLVER = "auto";

/**
 * Fetches available solvers on mount and manages selected solver state.
 * Silent fallback: dropdown still renders with "auto" when /solvers/available fails.
 */
export function useSolvers() {
  const [solverName, setSolverName] = useState<string>(DEFAULT_SOLVER);
  const [availableSolvers, setAvailableSolvers] = useState<SolverInfo[]>([]);
  const [solversLoading, setSolversLoading] = useState(true);

  useEffect(() => {
    api
      .getSolvers()
      .then((data) => {
        setAvailableSolvers(data.solvers);
      })
      .catch(() => { /* silent fallback */ })
      .finally(() => setSolversLoading(false));
  }, []);

  return { solverName, setSolverName, availableSolvers, solversLoading } as const;
}
