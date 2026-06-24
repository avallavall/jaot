"use client";

import { useState, useEffect, use } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { Workspace, WorkspaceMember, CreditPool } from "@/lib/types";
import { useAuth } from "@/contexts/AuthContext";
import { usePermission } from "@/hooks/usePermission";
import { useRoleDisplayName } from "@/components/workspaces/PermissionTooltip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { MemberTable } from "@/components/workspaces/MemberTable";
import { InviteDialog } from "@/components/workspaces/InviteDialog";
import { CreditPoolCard } from "@/components/workspaces/CreditPoolCard";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useTranslations } from "next-intl";
import { ArrowLeft, UserPlus } from "lucide-react";
import Link from "next/link";

interface WorkspaceDetailPageProps {
  params: Promise<{ workspaceId: string }>;
}

export default function WorkspaceDetailPage({ params }: WorkspaceDetailPageProps) {
  const { workspaceId } = use(params);
  const router = useRouter();
  const { setActiveWorkspace } = useAuth();
  const isAdmin = usePermission("admin");
  const roleName = useRoleDisplayName();
  const t = useTranslations("workspace.workspaceDetail");
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [pool, setPool] = useState<CreditPool | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("overview");
  const [inviteOpen, setInviteOpen] = useState(false);

  // Settings form state
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const [ws, memberList] = await Promise.all([
          api.getWorkspace(workspaceId),
          api.listMembers(workspaceId),
        ]);
        setWorkspace(ws);
        setMembers(memberList);
        setEditName(ws.name);
        setEditDescription(ws.description ?? "");

        // Load pool stats
        try {
          const poolData = await api.getPoolStats(workspaceId);
          setPool(poolData);
        } catch {
          // Pool may not exist yet
        }

        // Set as active workspace
        await setActiveWorkspace(workspaceId);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : t("loadError"));
        router.push("/workspace/workspaces");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [workspaceId, router, setActiveWorkspace, t]);

  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const updated = await api.updateWorkspace(workspaceId, {
        name: editName.trim(),
        description: editDescription.trim() || undefined,
      });
      setWorkspace(updated);
      toast.success(t("settingsSaved"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveError"));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="container mx-auto px-4 py-8 max-w-5xl">
        <Skeleton className="h-8 w-1/3 mb-2" />
        <Skeleton className="h-4 w-1/2 mb-8" />
        <div className="space-y-4">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      </div>
    );
  }

  if (!workspace) return null;

  return (
    <TooltipProvider>
      <div className="container mx-auto px-4 py-8 max-w-5xl">
        <div className="mb-6">
          <Button variant="ghost" size="sm" asChild className="mb-4 -ml-2">
            <Link href="/workspace/workspaces">
              <ArrowLeft className="w-4 h-4 mr-1" />
              {t("allWorkspaces")}
            </Link>
          </Button>
          <h1 className="text-3xl font-bold">{workspace.name}</h1>
          {workspace.description && (
            <p className="text-muted-foreground mt-1">{workspace.description}</p>
          )}
        </div>

        <Tabs defaultValue="overview" value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="mb-6">
            <TabsTrigger value="overview">{t("overview")}</TabsTrigger>
            <TabsTrigger value="members">
              {t("members", { count: members.length })}
            </TabsTrigger>
            <TabsTrigger value="settings">{t("settings")}</TabsTrigger>
          </TabsList>

          <TabsContent value="overview">
            <div className="grid gap-6 lg:grid-cols-2">
              <CreditPoolCard
                workspaceId={workspaceId}
                pool={pool}
                onPoolChange={setPool}
              />
              <div className="border rounded-lg p-6 bg-card">
                <h3 className="font-semibold mb-4">{t("team")}</h3>
                <p className="text-3xl font-bold text-primary mb-1">{members.length}</p>
                <p className="text-sm text-muted-foreground">
                  {members.length === 1 ? t("member") : t("membersPlural")}
                </p>
                <Button className="mt-4" variant="outline" size="sm" onClick={() => setActiveTab("members")}>
                  {t("viewMembers")}
                </Button>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="members">
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">{t("membersTitle")}</h2>
                {isAdmin ? (
                  <Button size="sm" onClick={() => setInviteOpen(true)}>
                    <UserPlus className="w-4 h-4 mr-2" />
                    {t("inviteMember")}
                  </Button>
                ) : (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span>
                        <Button size="sm" disabled>
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
              <MemberTable
                workspaceId={workspaceId}
                members={members}
                onMembersChange={setMembers}
              />
            </div>
          </TabsContent>

          <TabsContent value="settings">
            {isAdmin ? (
              <div className="max-w-lg">
                <h2 className="text-lg font-semibold mb-4">{t("workspaceSettings")}</h2>
                <form onSubmit={handleSaveSettings} className="space-y-4">
                  <div className="space-y-2">
                    <Label>{t("nameLabel")}</Label>
                    <Input
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      required
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>{t("descriptionLabel")}</Label>
                    <Textarea
                      value={editDescription}
                      onChange={(e) => setEditDescription(e.target.value)}
                      rows={3}
                    />
                  </div>
                  <Button type="submit" disabled={saving || !editName.trim()}>
                    {saving ? t("saving") : t("saveChanges")}
                  </Button>
                </form>
              </div>
            ) : (
              <div className="text-muted-foreground py-8 text-center max-w-md mx-auto">
                {t("adminOnlySettings", { role: roleName })}
              </div>
            )}
          </TabsContent>
        </Tabs>

        <InviteDialog
          workspaceId={workspaceId}
          open={inviteOpen}
          onClose={() => setInviteOpen(false)}
        />
      </div>
    </TooltipProvider>
  );
}
