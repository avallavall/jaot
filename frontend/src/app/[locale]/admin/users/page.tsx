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
import { toast } from "sonner";
import type { PaginatedResponse } from "@/lib/types";

interface AdminOrganizationSummary { id: string; name: string; }
interface AdminUser { id: string; name: string; email: string; organization_id: string; role: string; is_admin?: boolean; can_build_plugins?: boolean; is_active: boolean; created_at: string; last_login_at: string | null; updated_at: string; }

export default function UsersPage() {
  const t = useTranslations("admin.users");
  const tc = useTranslations("common");
  const dialog = useDialog();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [organizations, setOrganizations] = useState<AdminOrganizationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [orgFilter, setOrgFilter] = useState("");
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<AdminUser | null>(null);

  useEffect(() => {
    loadOrganizations();
  }, []);

  useEffect(() => {
    loadUsers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, search, orgFilter]);

  const loadOrganizations = async () => {
    try {
      const data = await api.admin.getOrganizations({ page_size: 100 }) as { items: AdminOrganizationSummary[] };
      setOrganizations(data.items);
    } catch (err) {
      console.warn('Failed to load organizations:', err);
    }
  };

  const loadUsers = async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await api.admin.getUsers({
        page,
        search: search || undefined,
        organization_id: orgFilter || undefined
      }) as unknown as PaginatedResponse<AdminUser>;
      setUsers(data.items);
      setTotalPages(data.total_pages ?? 1);
    } catch (err) {
      // Surface the failure instead of silently rendering "no users" — a failed
      // request and a genuinely empty list must not look identical.
      setLoadError(getErrorMessage(err, t("loadError")));
      setUsers([]);
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (formData: FormData) => {
    try {
      await api.admin.createUser({
        organization_id: formData.get("organization_id") as string,
        name: formData.get("name") as string,
        email: formData.get("email") as string || undefined,
        is_admin: formData.get("is_admin") === "on",
        can_build_plugins: formData.get("can_build_plugins") === "on",
      });
      setIsCreateOpen(false);
      loadUsers();
    } catch {
      toast.error(t("operationFailed"));
    }
  };

  const handleUpdateUser = async (formData: FormData) => {
    if (!editingUser) return;
    try {
      await api.request(`/api/v2/admin/users/${editingUser.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: formData.get("name") as string,
          email: formData.get("email") as string || null,
          is_admin: formData.get("is_admin") === "on",
          can_build_plugins: formData.get("can_build_plugins") === "on",
          is_active: formData.get("is_active") === "on",
        }),
      });
      setEditingUser(null);
      loadUsers();
    } catch {
      toast.error(t("operationFailed"));
    }
  };

  const handleDeleteUser = async (userId: string, userName: string) => {
    const confirmed = await dialog.confirm(
      t("deleteConfirm", { name: userName }),
      t("deleteTitle")
    );
    if (!confirmed) return;
    try {
      await api.request(`/api/v2/admin/users/${userId}`, { method: "DELETE" });
      loadUsers();
    } catch {
      toast.error(t("operationFailed"));
    }
  };

  const getOrgName = (orgId: string) => {
    const org = organizations.find(o => o.id === orgId);
    return org?.name || orgId;
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
              {t("newUser")}
            </Button>
          </DialogTrigger>
          <DialogContent className="border-border">
            <DialogHeader>
              <DialogTitle className="font-serif">{t("createUser")}</DialogTitle>
            </DialogHeader>
            <form action={handleCreate} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="organization_id">{t("organizationLabel")}</Label>
                <select
                  id="organization_id"
                  name="organization_id"
                  required
                  className="w-full p-2 border border-input bg-background"
                >
                  <option value="">{t("selectOrg")}</option>
                  {organizations.map(org => (
                    <option key={org.id} value={org.id}>{org.name}</option>
                  ))}
                </select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="name">{t("nameLabel")}</Label>
                <Input id="name" name="name" required />
              </div>
              <div className="space-y-2">
                <Label htmlFor="email">{t("emailLabel")}</Label>
                <Input id="email" name="email" type="email" />
              </div>
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2">
                  <input type="checkbox" id="is_admin" name="is_admin" />
                  <Label htmlFor="is_admin">{t("isAdmin")}</Label>
                </div>
                <div className="flex items-center gap-2">
                  <input type="checkbox" id="can_build_plugins" name="can_build_plugins" />
                  <Label htmlFor="can_build_plugins">{t("canBuildPlugins")}</Label>
                </div>
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
          <div className="flex gap-4">
            <Input
              placeholder={t("searchPlaceholder")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="max-w-xs"
            />
            <select
              value={orgFilter}
              onChange={(e) => setOrgFilter(e.target.value)}
              className="p-2 border border-input bg-background text-sm"
            >
              <option value="">{t("allOrganizations")}</option>
              {organizations.map(org => (
                <option key={org.id} value={org.id}>{org.name}</option>
              ))}
            </select>
          </div>
        </CardContent>
      </Card>

      <Card className="border-border">
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow className="border-border">
                <TableHead>{t("tableHeaders.name")}</TableHead>
                <TableHead>{t("tableHeaders.email")}</TableHead>
                <TableHead>{t("tableHeaders.organization")}</TableHead>
                <TableHead>{t("tableHeaders.role")}</TableHead>
                <TableHead>{t("tableHeaders.builder")}</TableHead>
                <TableHead>{t("tableHeaders.status")}</TableHead>
                <TableHead>{t("tableHeaders.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                    {tc("loading")}
                  </TableCell>
                </TableRow>
              ) : loadError ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-8">
                    <p className="text-destructive mb-3">{loadError}</p>
                    <Button variant="outline" size="sm" onClick={loadUsers}>
                      {t("retry")}
                    </Button>
                  </TableCell>
                </TableRow>
              ) : users.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                    {t("noUsers")}
                  </TableCell>
                </TableRow>
              ) : (
                users.map((user) => (
                  <TableRow key={user.id} className="border-border">
                    <TableCell className="font-medium">{user.name}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {user.email || "-"}
                    </TableCell>
                    <TableCell>{getOrgName(user.organization_id)}</TableCell>
                    <TableCell>
                      <Badge variant={user.is_admin ? "default" : "outline"}>
                        {user.is_admin ? t("admin") : t("member")}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {user.can_build_plugins ? (
                        <Badge variant="secondary">{t("canBuild")}</Badge>
                      ) : (
                        <span className="text-muted-foreground">{t("cannotBuild")}</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant={user.is_active ? "default" : "secondary"}>
                        {user.is_active ? t("active") : t("inactive")}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setEditingUser(user)}
                        >
                          {t("edit")}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive hover:text-destructive"
                          onClick={() => handleDeleteUser(user.id, user.name)}
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

      <Dialog open={!!editingUser} onOpenChange={(open) => !open && setEditingUser(null)}>
        <DialogContent className="border-border">
          <DialogHeader>
            <DialogTitle className="font-serif">{t("editUser")}</DialogTitle>
          </DialogHeader>
          {editingUser && (
            <form action={handleUpdateUser} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="edit-name">{t("nameLabel")}</Label>
                <Input id="edit-name" name="name" defaultValue={editingUser.name} required />
              </div>
              <div className="space-y-2">
                <Label htmlFor="edit-email">{t("emailLabel")}</Label>
                <Input id="edit-email" name="email" type="email" defaultValue={editingUser.email || ""} />
              </div>
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="edit-is_admin"
                    name="is_admin"
                    defaultChecked={editingUser.is_admin}
                  />
                  <Label htmlFor="edit-is_admin">{t("isAdmin")}</Label>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="edit-can_build_plugins"
                    name="can_build_plugins"
                    defaultChecked={editingUser.can_build_plugins}
                  />
                  <Label htmlFor="edit-can_build_plugins">{t("canBuildShort")}</Label>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="edit-is_active"
                    name="is_active"
                    defaultChecked={editingUser.is_active}
                  />
                  <Label htmlFor="edit-is_active">{t("activeLabel")}</Label>
                </div>
              </div>
              <div className="flex gap-2">
                <Button type="submit" className="flex-1 bg-primary text-primary-foreground">
                  {t("saveChanges")}
                </Button>
                <Button type="button" variant="outline" onClick={() => setEditingUser(null)}>
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
