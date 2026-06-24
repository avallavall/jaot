"use client";

import { useState } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { WorkspaceInvite, WorkspaceRole } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { useTranslations } from "next-intl";
import { Copy, Check, Trash2, UserPlus } from "lucide-react";

interface InviteDialogProps {
  workspaceId: string;
  open: boolean;
  onClose: () => void;
}

const ROLES: WorkspaceRole[] = ["admin", "editor", "solver", "viewer"];

const ROLE_COLORS: Record<WorkspaceRole, string> = {
  admin: "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400",
  editor: "bg-blue-100 text-blue-800 dark:bg-blue-900/20 dark:text-blue-400",
  solver: "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400",
  viewer: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400",
};

function formatExpiry(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString();
}

export function InviteDialog({ workspaceId, open, onClose }: InviteDialogProps) {
  const t = useTranslations("workspace.invite");
  const [emailInput, setEmailInput] = useState("");
  const [emailRole, setEmailRole] = useState<WorkspaceRole>("solver");
  const [linkRole, setLinkRole] = useState<WorkspaceRole>("solver");
  const [sendingEmail, setSendingEmail] = useState(false);
  const [generatingLink, setGeneratingLink] = useState(false);
  const [generatedLink, setGeneratedLink] = useState<string | null>(null);
  const [linkExpiresAt, setLinkExpiresAt] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [pendingInvites, setPendingInvites] = useState<WorkspaceInvite[]>([]);
  const [invitesLoaded, setInvitesLoaded] = useState(false);
  const [loadingInvites, setLoadingInvites] = useState(false);

  const loadInvites = async () => {
    if (invitesLoaded) return;
    setLoadingInvites(true);
    try {
      const data = await api.listInvites(workspaceId);
      setPendingInvites(data.filter((i) => !i.is_revoked));
      setInvitesLoaded(true);
    } catch (err) {
      console.warn('Failed to load invites:', err);
    } finally {
      setLoadingInvites(false);
    }
  };

  const handleSendEmail = async () => {
    if (!emailInput.trim()) return;
    setSendingEmail(true);
    try {
      const invite = await api.createEmailInvite(workspaceId, {
        email: emailInput.trim(),
        role: emailRole,
      });
      toast.success(t("sentSuccess", { email: emailInput.trim() }));
      setEmailInput("");
      setPendingInvites((prev) => [...prev, invite]);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("sendError"));
    } finally {
      setSendingEmail(false);
    }
  };

  const handleGenerateLink = async () => {
    setGeneratingLink(true);
    try {
      const result = await api.createLinkInvite(workspaceId, { role: linkRole });
      setGeneratedLink(result.invite_url);
      setLinkExpiresAt(result.expires_at);
      toast.success(t("linkGenerated"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("generateError"));
    } finally {
      setGeneratingLink(false);
    }
  };

  const handleCopyLink = async () => {
    if (!generatedLink) return;
    try {
      await navigator.clipboard.writeText(generatedLink);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(t("copyFailed"));
    }
  };

  const handleRevoke = async (invite: WorkspaceInvite) => {
    try {
      await api.revokeInvite(workspaceId, invite.id);
      setPendingInvites((prev) => prev.filter((i) => i.id !== invite.id));
      toast.success(t("revoked"));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("revokeError"));
    }
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onClose(); }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <UserPlus className="w-5 h-5 text-primary" />
            {t("title")}
          </DialogTitle>
        </DialogHeader>

        <div>
          <Tabs defaultValue="email" onValueChange={() => { if (!invitesLoaded) loadInvites(); }}>
            <TabsList className="mb-4">
              <TabsTrigger value="email">{t("emailInvite")}</TabsTrigger>
              <TabsTrigger value="link">{t("shareableLink")}</TabsTrigger>
            </TabsList>

            <TabsContent value="email" className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="invite-email">{t("emailLabel")}</Label>
                <Input
                  id="invite-email"
                  type="email"
                  placeholder={t("emailPlaceholder")}
                  value={emailInput}
                  onChange={(e) => setEmailInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleSendEmail()}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="invite-email-role">{t("roleLabel")}</Label>
                <Select value={emailRole} onValueChange={(v) => setEmailRole(v as WorkspaceRole)}>
                  <SelectTrigger id="invite-email-role">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ROLES.map((r) => (
                      <SelectItem key={r} value={r}>
                        {t(`roles.${r}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Button
                onClick={handleSendEmail}
                disabled={!emailInput.trim() || sendingEmail}
                className="w-full"
              >
                {sendingEmail ? t("sending") : t("sendInvite")}
              </Button>
            </TabsContent>

            <TabsContent value="link" className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="invite-link-role">{t("roleLinkLabel")}</Label>
                <Select value={linkRole} onValueChange={(v) => setLinkRole(v as WorkspaceRole)}>
                  <SelectTrigger id="invite-link-role">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ROLES.map((r) => (
                      <SelectItem key={r} value={r}>
                        {t(`roles.${r}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {generatedLink ? (
                <div className="space-y-2">
                  <Label htmlFor="invite-generated-link">{t("inviteLink")}</Label>
                  <div className="flex gap-2">
                    <Input id="invite-generated-link" value={generatedLink} readOnly className="font-mono text-xs" />
                    <Button variant="outline" size="sm" onClick={handleCopyLink}>
                      {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                    </Button>
                  </div>
                  {linkExpiresAt && (
                    <p className="text-xs text-muted-foreground">
                      {t("expiresLabel", { date: formatExpiry(linkExpiresAt) })}
                    </p>
                  )}
                </div>
              ) : (
                <Button
                  onClick={handleGenerateLink}
                  disabled={generatingLink}
                  className="w-full"
                >
                  {generatingLink ? t("generating") : t("generateLink")}
                </Button>
              )}
            </TabsContent>
          </Tabs>

          {invitesLoaded && pendingInvites.length > 0 && (
            <div className="mt-4 border-t pt-4">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                {t("pendingInvites", { count: pendingInvites.length })}
              </h3>
              <div className="space-y-2 max-h-40 overflow-y-auto">
                {pendingInvites.map((invite) => (
                  <div
                    key={invite.id}
                    className="flex items-center justify-between gap-2 text-sm"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <Badge
                        className={`${ROLE_COLORS[invite.role]} border-0 capitalize text-xs shrink-0`}
                      >
                        {invite.role}
                      </Badge>
                      <span className="text-muted-foreground truncate">
                        {invite.invitee_email ?? `Link \u2022 expires ${formatExpiry(invite.expires_at)}`}
                      </span>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleRevoke(invite)}
                      className="text-muted-foreground hover:text-destructive h-6 w-6 p-0 shrink-0"
                      title={t("revoked")}
                    >
                      <Trash2 className="w-3 h-3" />
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          )}
          {loadingInvites && (
            <p className="text-xs text-muted-foreground mt-4">{t("loadingPending")}</p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("close")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
