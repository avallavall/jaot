"use client";

import { useTranslations } from "next-intl";
import { useAuth } from "@/contexts/AuthContext";
import type { WorkspaceRole } from "@/lib/types";
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
 * Hook that returns a function naming a workspace role in the reader's language.
 *
 * The role values are English words ("admin", "viewer"), and the member table,
 * its badge and the role-change toast printed them as they came, in every locale.
 */
export function useRoleLabel(): (role: WorkspaceRole | null | undefined) => string {
  const t = useTranslations("workspace.invite.roles");
  return (role) => (role ? t(role) : t("member"));
}

/**
 * Hook that returns the display name for the current user's workspace role.
 * Falls back to "Member" if no role is set.
 */
export function useRoleDisplayName(): string {
  const { workspaceRole } = useAuth();
  return useRoleLabel()(workspaceRole);
}
