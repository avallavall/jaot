import { useAuth } from "@/contexts/AuthContext";
import type { WorkspaceRole } from "@/lib/types";

const ROLE_ORDER: WorkspaceRole[] = ["viewer", "solver", "editor", "admin"];

function hasMinimumRole(
  userRole: WorkspaceRole | null,
  required: WorkspaceRole
): boolean {
  if (!userRole || !required) return false;
  return ROLE_ORDER.indexOf(userRole) >= ROLE_ORDER.indexOf(required);
}

export function usePermission(requiredRole: WorkspaceRole): boolean {
  const { isOwner, workspaceRole } = useAuth();
  if (isOwner) return true;
  return hasMinimumRole(workspaceRole, requiredRole);
}
