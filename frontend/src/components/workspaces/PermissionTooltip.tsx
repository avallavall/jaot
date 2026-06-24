"use client";

import { useAuth } from "@/contexts/AuthContext";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface PermissionTooltipProps {
  /** The i18n-translated message. Should contain a {role} placeholder already filled. */
  readonly message: string;
  readonly children: React.ReactNode;
  /** Whether the permission check failed (tooltip only shows when true). */
  readonly show: boolean;
}

/**
 * Wraps a disabled button with a tooltip showing a role-specific permission message.
 * Only renders the tooltip when `show` is true; otherwise renders children directly.
 */
export function PermissionTooltip({ message, children, show }: PermissionTooltipProps) {
  if (!show) return <>{children}</>;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span>{children}</span>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs text-center">
        {message}
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * Hook that returns the display name for the current user's workspace role.
 * Falls back to "Member" if no role is set.
 */
export function useRoleDisplayName(): string {
  const { workspaceRole } = useAuth();
  if (!workspaceRole) return "Member";
  return workspaceRole.charAt(0).toUpperCase() + workspaceRole.slice(1);
}
