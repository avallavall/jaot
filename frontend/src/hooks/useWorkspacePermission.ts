import { useAuth } from "@/contexts/AuthContext";
import { usePermission } from "@/hooks/usePermission";
import type { WorkspaceRole } from "@/lib/types";

/**
 * Workspace-aware permission check.
 * Returns true when no workspace is active (org-level access, no role restriction).
 * Delegates to usePermission when a workspace IS active.
 */
export function useWorkspacePermission(requiredRole: WorkspaceRole): boolean {
  const { activeWorkspaceId } = useAuth();
  const hasRole = usePermission(requiredRole);
  if (!activeWorkspaceId) return true;
  return hasRole;
}
