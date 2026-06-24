"use client";

import { useState, useEffect } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { WorkspaceMember } from "@/lib/types";
import { useAuth } from "@/contexts/AuthContext";
import { usePermission } from "@/hooks/usePermission";
import { useRoleDisplayName } from "@/components/workspaces/PermissionTooltip";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Skeleton } from "@/components/ui/skeleton";
import { MemberTable } from "@/components/workspaces/MemberTable";
import { InviteDialog } from "@/components/workspaces/InviteDialog";
import { QuickStartGuide } from "@/components/workspaces/QuickStartGuide";
import { useTranslations } from "next-intl";
import { Building2, UserPlus } from "lucide-react";
import Link from "next/link";

export default function TeamPage() {
  const { activeWorkspaceId, isOwner } = useAuth();
  const isAdmin = usePermission("admin");
  const roleName = useRoleDisplayName();
  const t = useTranslations("workspace.team");
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [loading, setLoading] = useState(false);
  const [inviteOpen, setInviteOpen] = useState(false);

  useEffect(() => {
    if (!activeWorkspaceId) return;
    const load = async () => {
      setLoading(true);
      try {
        const data = await api.listMembers(activeWorkspaceId);
        setMembers(data);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : t("loadError"));
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [activeWorkspaceId, t]);

  // No workspace selected
  if (!activeWorkspaceId) {
    return (
      <div className="container mx-auto px-4 py-8 max-w-5xl">
        <h1 className="text-3xl font-bold mb-2">{t("title")}</h1>
        <p className="text-muted-foreground mb-8">{t("subtitle")}</p>
        <div className="text-center py-16 bg-card border-2 border-dashed rounded-xl">
          <Building2 className="w-12 h-12 mx-auto text-muted-foreground/40 mb-4" />
          <h2 className="text-xl font-semibold mb-2">{t("noWorkspace")}</h2>
          <p className="text-muted-foreground mb-6">
            {t("noWorkspaceDescription")}
          </p>
          <div className="flex items-center justify-center gap-3">
            {isOwner && (
              <Button asChild>
                <Link href="/workspace/workspaces/new">{t("createWorkspace")}</Link>
              </Button>
            )}
            <Button variant={isOwner ? "outline" : "default"} asChild>
              <Link href="/workspace/workspaces">{t("browseWorkspaces")}</Link>
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <TooltipProvider>
      <div className="container mx-auto px-4 py-8 max-w-5xl">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold mb-2">{t("title")}</h1>
            <p className="text-muted-foreground">{t("membersSubtitle")}</p>
          </div>
          {isAdmin ? (
            <Button onClick={() => setInviteOpen(true)}>
              <UserPlus className="w-4 h-4 mr-2" />
              {t("inviteMember")}
            </Button>
          ) : (
            <Tooltip>
              <TooltipTrigger asChild>
                <span>
                  <Button disabled>
                    <UserPlus className="w-4 h-4 mr-2" />
                    {t("inviteMember")}
                  </Button>
                </span>
              </TooltipTrigger>
              <TooltipContent className="max-w-xs text-center">
                {t("adminRequired", { role: roleName })}
              </TooltipContent>
            </Tooltip>
          )}
        </div>

        <QuickStartGuide />

        {loading && (
          <div className="space-y-3">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="border rounded-lg p-4 flex items-center gap-4">
                <Skeleton className="h-8 w-8 rounded-full" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-1/4" />
                  <Skeleton className="h-3 w-1/3" />
                </div>
              </div>
            ))}
          </div>
        )}

        {!loading && (
          <MemberTable
            workspaceId={activeWorkspaceId}
            members={members}
            onMembersChange={setMembers}
          />
        )}

        <InviteDialog
          workspaceId={activeWorkspaceId}
          open={inviteOpen}
          onClose={() => setInviteOpen(false)}
        />
      </div>
    </TooltipProvider>
  );
}
