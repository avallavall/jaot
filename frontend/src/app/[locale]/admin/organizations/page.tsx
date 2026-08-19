"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";
import { useDialog } from "@/components/ui/dialog-custom";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { toast } from "sonner";
import type { AdminListResponse } from "@/lib/types";

interface AdminOrganization {
  id: string;
  name: string;
  user_count?: number;
  is_verified: boolean;
  is_active: boolean;
  ai_builder_enabled?: boolean;
  created_at: string;
}

export default function OrganizationsPage() {
  const t = useTranslations("admin.organizations");
  const tc = useTranslations("common");
  const dialog = useDialog();
  const [organizations, setOrganizations] = useState<AdminOrganization[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [editingOrg, setEditingOrg] = useState<AdminOrganization | null>(null);

  useEffect(() => {
    loadOrganizations();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, search]);

  const loadOrganizations = async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await api.admin.getOrganizations({ page, search }) as AdminListResponse<AdminOrganization>;
      setOrganizations(data.items);
      setTotalPages(data.pages ?? 1);
    } catch (err) {
      // Surface the failure instead of silently rendering an empty table —
      // an empty list and a failed request must not look the same.
      setLoadError(getErrorMessage(err, t("loadError")));
      setOrganizations([]);
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (formData: FormData) => {
    try {
      await api.admin.createOrganization({
        name: formData.get("name") as string,
        ai_builder_enabled: formData.get("ai_builder") === "on",
      });
      setIsCreateOpen(false);
      loadOrganizations();
    } catch {
      toast.error(t("operationFailed"));
    }
  };

  const handleToggleVerified = async (orgId: string, currentVerified: boolean) => {
    try {
      await api.admin.updateOrganization(orgId, { is_verified: !currentVerified });
      loadOrganizations();
    } catch {
      toast.error(t("operationFailed"));
    }
  };

  const handleUpdateOrg = async (formData: FormData) => {
    if (!editingOrg) return;
    try {
      await api.admin.updateOrganization(editingOrg.id, {
        name: formData.get("name") as string,
        is_active: formData.get("is_active") === "on",
        ai_builder_enabled: formData.get("ai_builder") === "on",
      });
      setEditingOrg(null);
      loadOrganizations();
    } catch {
      toast.error(t("operationFailed"));
    }
  };

  const handleDeleteOrg = async (orgId: string, orgName: string) => {
    const confirmed = await dialog.confirm(
      t("deleteConfirm", { name: orgName }),
      t("deleteTitle")
    );
    if (!confirmed) return;
    try {
      await api.request(`/api/v2/admin/organizations/${orgId}`, { method: "DELETE" });
      loadOrganizations();
    } catch {
      toast.error(t("operationFailed"));
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-serif text-foreground">{t("title")}</h1>
          <p className="text-muted-foreground mt-1">
            {t("subtitle")}
          </p>
        </div>

        <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
          <DialogTrigger asChild>
            <Button className="bg-primary text-primary-foreground">
              {t("newOrganization")}
            </Button>
          </DialogTrigger>
          <DialogContent className="border-border">
            <DialogHeader>
              <DialogTitle className="font-serif">{t("createOrganization")}</DialogTitle>
            </DialogHeader>
            <form action={handleCreate} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="name">{t("nameLabel")}</Label>
                <Input id="name" name="name" required />
              </div>
              <div className="flex items-center gap-2">
                <input type="checkbox" id="ai_builder" name="ai_builder" />
                <Label htmlFor="ai_builder">{t("enableAiBuilder")}</Label>
              </div>
              <Button type="submit" className="w-full bg-primary text-primary-foreground">
                {t("create")}
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <Card className="border-border">
        <CardContent className="pt-4">
          <Input
            placeholder={t("searchPlaceholder")}
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            className="max-w-sm"
          />
        </CardContent>
      </Card>

      <Card className="border-border">
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow className="border-border">
                <TableHead>{t("tableHeaders.name")}</TableHead>
                <TableHead>{t("tableHeaders.users")}</TableHead>
                <TableHead>{t("tableHeaders.verified")}</TableHead>
                <TableHead>{t("tableHeaders.status")}</TableHead>
                <TableHead>{t("tableHeaders.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center py-8 text-muted-foreground">
                    {tc("loading")}
                  </TableCell>
                </TableRow>
              ) : loadError ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center py-8">
                    <p className="text-destructive mb-3">{loadError}</p>
                    <Button variant="outline" size="sm" onClick={loadOrganizations}>
                      {t("retry")}
                    </Button>
                  </TableCell>
                </TableRow>
              ) : organizations.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center py-8 text-muted-foreground">
                    {t("noOrganizations")}
                  </TableCell>
                </TableRow>
              ) : (
                organizations.map((org) => (
                  <TableRow key={org.id} className="border-border">
                    <TableCell className="font-medium">{org.name}</TableCell>
                    <TableCell>{org.user_count || 0}</TableCell>
                    <TableCell>
                      <button
                        onClick={() => handleToggleVerified(org.id, org.is_verified)}
                        className={`px-2 py-0.5 text-xs rounded cursor-pointer transition-colors ${
                          org.is_verified
                            ? 'bg-blue-100 text-blue-800 hover:bg-blue-200'
                            : 'bg-gray-100 text-gray-400 hover:bg-gray-200'
                        }`}
                      >
                        {org.is_verified ? `✓ ${t("verified")}` : t("unverified")}
                      </button>
                    </TableCell>
                    <TableCell>
                      <Badge variant={org.is_active ? "default" : "secondary"}>
                        {org.is_active ? t("active") : t("inactive")}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Button variant="ghost" size="sm" asChild>
                          <Link href={`/admin/organizations/${org.id}`}>{t("view")}</Link>
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setEditingOrg(org)}
                        >
                          {t("edit")}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive hover:text-destructive"
                          onClick={() => handleDeleteOrg(org.id, org.name)}
                        >
                          {t("delete")}
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page === 1}
          >
            {tc("previous")}
          </Button>
          <span className="text-sm text-muted-foreground">
            {t("pageOf", { page, totalPages })}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
          >
            {tc("next")}
          </Button>
        </div>
      )}

      <Dialog open={!!editingOrg} onOpenChange={(open) => !open && setEditingOrg(null)}>
        <DialogContent className="border-border">
          <DialogHeader>
            <DialogTitle className="font-serif">{t("editOrganization")}</DialogTitle>
          </DialogHeader>
          {editingOrg && (
            <form action={handleUpdateOrg} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="edit-name">{t("nameLabel")}</Label>
                <Input id="edit-name" name="name" defaultValue={editingOrg.name} required />
              </div>
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="edit-is_active"
                    name="is_active"
                    defaultChecked={editingOrg.is_active}
                  />
                  <Label htmlFor="edit-is_active">{t("activeLabel")}</Label>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="edit-ai_builder"
                    name="ai_builder"
                    defaultChecked={editingOrg.ai_builder_enabled}
                  />
                  <Label htmlFor="edit-ai_builder">{t("aiBuilder")}</Label>
                </div>
              </div>
              <div className="flex gap-2">
                <Button type="submit" className="flex-1 bg-primary text-primary-foreground">
                  {t("saveChanges")}
                </Button>
                <Button type="button" variant="outline" onClick={() => setEditingOrg(null)}>
                  {tc("cancel")}
                </Button>
              </div>
            </form>
          )}
        </DialogContent>
      </Dialog>

      <dialog.DialogComponent />
    </div>
  );
}
