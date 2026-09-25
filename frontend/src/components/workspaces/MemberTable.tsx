"use client";

import { useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { WorkspaceMember, WorkspaceRole } from "@/lib/types";
import { usePermission } from "@/hooks/usePermission";
import { useAuth } from "@/contexts/AuthContext";
import { translateApiError } from "@/lib/errors";
import { useRoleLabel } from "@/components/workspaces/PermissionTooltip";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useDialog } from "@/components/ui/dialog-custom";
import { useTranslations } from "next-intl";
import { X } from "lucide-react";
import { useDateFormat } from "@/hooks/useDateFormat";

interface MemberTableProps {
  workspaceId: string;
  members: WorkspaceMember[];
  onMembersChange: (members: WorkspaceMember[]) => void;
}

const ROLE_COLORS: Record<WorkspaceRole, string> = {
  admin: "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400",
  editor: "bg-blue-100 text-blue-800 dark:bg-blue-900/20 dark:text-blue-400",
  solver: "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400",
  viewer: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400",
};

const ROLES: WorkspaceRole[] = ["admin", "editor", "solver", "viewer"];

function getInitials(name: string): string {
  return name
    .split(" ")
    .map((n) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);
}

export function MemberTable({ workspaceId, members, onMembersChange }: MemberTableProps) {
  const dialog = useDialog();
  const isAdmin = usePermission("admin");
  const { user } = useAuth();
  const t = useTranslations("workspace.memberTable");
  const tError = useTranslations("errors.codes");
  const roleLabel = useRoleLabel();
  const { day } = useDateFormat();
  const [updatingRole, setUpdatingRole] = useState<Record<string, boolean>>({});

  // The server refuses both a role change and a removal for your own row and
  // for the organization owner's. The select and the X used to be offered there
  // anyway, and every use ended in an error.
  const canManage = (member: WorkspaceMember) =>
    isAdmin && member.user_id !== user?.id && !member.is_org_owner;

  const handleRoleChange = async (member: WorkspaceMember, newRole: WorkspaceRole) => {
    if (newRole === member.role) return;
    setUpdatingRole((prev) => ({ ...prev, [member.user_id]: true }));
    try {
      await api.updateMemberRole(workspaceId, member.user_id, newRole);
      onMembersChange(
        members.map((m) => (m.user_id === member.user_id ? { ...m, role: newRole } : m))
      );
      toast.success(t("roleUpdated", { name: member.user_name, role: roleLabel(newRole) }));
    } catch (err) {
      toast.error(translateApiError(err, tError, t("roleError")));
    } finally {
      setUpdatingRole((prev) => ({ ...prev, [member.user_id]: false }));
    }
  };

  const handleRemoveMember = (member: WorkspaceMember) => {
    dialog.confirmCallback(
      t("removeConfirm", { name: member.user_name }),
      async () => {
        try {
          await api.removeMember(workspaceId, member.user_id);
          onMembersChange(members.filter((m) => m.user_id !== member.user_id));
          toast.success(t("removed", { name: member.user_name }));
        } catch (err) {
          toast.error(translateApiError(err, tError, t("removeError")));
        }
      },
      t("removeTitle")
    );
  };

  if (members.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        {t("noMembers")}
      </div>
    );
  }

  return (
    <TooltipProvider>
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/50">
              <th className="text-left px-4 py-3 font-medium text-muted-foreground">{t("headers.member")}</th>
              <th className="text-left px-4 py-3 font-medium text-muted-foreground">{t("headers.email")}</th>
              <th className="text-left px-4 py-3 font-medium text-muted-foreground">{t("headers.role")}</th>
              <th className="text-left px-4 py-3 font-medium text-muted-foreground">{t("headers.joined")}</th>
              {isAdmin && (
                <th className="text-right px-4 py-3 font-medium text-muted-foreground">{t("headers.actions")}</th>
              )}
            </tr>
          </thead>
          <tbody>
            {members.map((member) => (
              <tr key={member.user_id} className="border-b last:border-0 hover:bg-muted/20">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-xs font-semibold text-primary shrink-0">
                      {getInitials(member.user_name)}
                    </div>
                    <span className="font-medium">{member.user_name}</span>
                  </div>
                </td>
                <td className="px-4 py-3 text-muted-foreground">{member.user_email}</td>
                <td className="px-4 py-3">
                  {canManage(member) ? (
                    <Select
                      value={member.role}
                      onValueChange={(val) => handleRoleChange(member, val as WorkspaceRole)}
                      disabled={updatingRole[member.user_id]}
                    >
                      <SelectTrigger
                        className="w-28 h-7 text-xs"
                        aria-label={t("roleOf", { name: member.user_name })}
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {ROLES.map((role) => (
                          <SelectItem key={role} value={role} className="text-xs">
                            {roleLabel(role)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <Badge className={`${ROLE_COLORS[member.role]} border-0 font-medium`}>
                      {roleLabel(member.role)}
                    </Badge>
                  )}
                </td>
                <td className="px-4 py-3 text-muted-foreground">{day(member.joined_at)}</td>
                {isAdmin && (
                  <td className="px-4 py-3 text-right">
                    {canManage(member) && (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleRemoveMember(member)}
                            className="text-muted-foreground hover:text-destructive h-7 w-7 p-0"
                            aria-label={t("removeMemberNamed", { name: member.user_name })}
                          >
                            <X className="w-4 h-4" aria-hidden="true" />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>{t("removeMember")}</TooltipContent>
                      </Tooltip>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dialog.DialogComponent />
    </TooltipProvider>
  );
}
