"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { SolverCapabilities, SolverInfo } from "@/lib/types";

// Re-exported so existing importers keep working; the canonical declaration
// lives in lib/types.ts next to the rest of the handwritten API types.
export type { SolverCapabilities, SolverInfo };

// "auto" is the server-side routed pseudo-solver — backend picks the effective solver per problem.
const DEFAULT_SOLVER = "auto";

/**
 * Capabilities of `name` within an already-fetched listing.
 *
 * Returns `undefined` for "auto" ON PURPOSE: the effective solver is chosen by
 * the backend per problem, so nothing can be promised about it up front.
 */
export function capabilitiesOf(
  solvers: SolverInfo[],
  name: string | null | undefined
): SolverCapabilities | undefined {
  if (!name || name === DEFAULT_SOLVER) return undefined;
  const target = name.toLowerCase();
  return solvers.find((s) => s.name.toLowerCase() === target)?.capabilities;
}

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

/**
 * Capabilities of the solver that ran a PAST execution, looked up by name.
 *
 * The listing is the single source of truth (see the endpoint docstring), so a
 * solver that is no longer listed — or a lookup that failed — yields
 * `undefined` and callers must fall back to claiming nothing rather than
 * assuming the reference adapter's feature set.
 */
export function useSolverCapabilities(
  solverName: string | null | undefined
): SolverCapabilities | undefined {
  const [solvers, setSolvers] = useState<SolverInfo[]>([]);

  useEffect(() => {
    if (!solverName) return;
    let cancelled = false;
    api
      .getSolvers()
      .then((data) => {
        if (!cancelled) setSolvers(data.solvers);
      })
      .catch(() => { /* silent: unknown capabilities read as "claim nothing" */ });
    return () => {
      cancelled = true;
    };
  }, [solverName]);

  return capabilitiesOf(solvers, solverName);
}
