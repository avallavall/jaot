"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ProjectDatasetSummary } from "@/lib/types";

/**
 * The project's datasets ("scenarios") — compact rows, refetched on mount and on
 * demand (`refresh` after a create/update/delete). Shared by the Analyze card and
 * the JModel lens' dataset selector; both mount/unmount with their lens, so a
 * change made in one is picked up by the other on its next mount.
 */
export function useProjectDatasets(projectId: string | null): {
  datasets: ProjectDatasetSummary[];
  refresh: () => void;
} {
  const [datasets, setDatasets] = useState<ProjectDatasetSummary[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    if (!projectId || projectId === "new") return;
    let cancelled = false;
    api
      .listProjectDatasets(projectId)
      .then((rows) => {
        if (!cancelled) setDatasets(rows);
      })
      .catch(() => {
        /* the selector/card just stays empty — not a blocking surface */
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, refreshKey]);

  return { datasets, refresh };
}
