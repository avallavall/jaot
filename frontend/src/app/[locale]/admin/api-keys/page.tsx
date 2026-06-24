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
import { useTranslations } from "next-intl";
import type { PaginatedResponse } from "@/lib/types";

interface AdminOrganizationSummary { id: string; name: string; }
interface AdminUserSummary { id: string; name: string; }
interface AdminAPIKey { id: string; name: string; description?: string; key_prefix: string; organization_id: string; user_id: string; is_active: boolean; created_at: string; last_used_at: string | null; full_key?: string; }

export default function APIKeysPage() {
  const t = useTranslations("admin.apiKeys");
  const tc = useTranslations("common");
  const [apiKeys, setApiKeys] = useState<AdminAPIKey[]>([]);
  const [organizations, setOrganizations] = useState<AdminOrganizationSummary[]>([]);
  const [users, setUsers] = useState<AdminUserSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [orgFilter, setOrgFilter] = useState("");
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [newKey, setNewKey] = useState<string | null>(null);
  const [selectedOrg, setSelectedOrg] = useState("");

  useEffect(() => {
    loadOrganizations();
  }, []);

  useEffect(() => {
    loadApiKeys();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, orgFilter]);

  useEffect(() => {
    if (selectedOrg) {
      loadUsers(selectedOrg);
    }
  }, [selectedOrg]);

  const loadOrganizations = async () => {
    try {
      const data = await api.admin.getOrganizations({ page_size: 100 }) as { items: AdminOrganizationSummary[] };
      setOrganizations(data.items);
    } catch (err) {
      console.warn('Failed to load organizations:', err);
    }
  };

  const loadUsers = async (orgId: string) => {
    try {
      const data = await api.admin.getUsers({ organization_id: orgId, page_size: 100 }) as { items: AdminUserSummary[] };
      setUsers(data.items);
    } catch (err) {
      console.warn('Failed to load users:', err);
    }
  };

  const loadApiKeys = async () => {
    setLoading(true);
    try {
      const data = await api.admin.getApiKeys({
        page,
        organization_id: orgFilter || undefined
      }) as PaginatedResponse<AdminAPIKey>;
      setApiKeys(data.items);
      setTotalPages(data.total_pages ?? 1);
    } catch (err) {
      console.warn('Failed to load API keys:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (formData: FormData) => {
    try {
      const result = await api.admin.createApiKey({
        organization_id: formData.get("organization_id") as string,
        user_id: formData.get("user_id") as string,
        name: formData.get("name") as string,
        description: formData.get("description") as string || undefined,
      }) as AdminAPIKey;

      if (result.full_key) {
        setNewKey(result.full_key);
      }
      loadApiKeys();
    } catch {
      // Failed to create API key
    }
  };

  const getOrgName = (orgId: string) => {
    const org = organizations.find(o => o.id === orgId);
    return org?.name || orgId;
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return "-";
    return new Date(dateStr).toLocaleDateString();
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
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

        <Dialog open={isCreateOpen} onOpenChange={(open) => {
          setIsCreateOpen(open);
          if (!open) {
            setNewKey(null);
            setSelectedOrg("");
            setUsers([]);
          }
        }}>
          <DialogTrigger asChild>
            <Button className="bg-primary text-primary-foreground">
              {t("newApiKey")}
            </Button>
          </DialogTrigger>
          <DialogContent className="border-border">
            <DialogHeader>
              <DialogTitle className="font-serif">
                {newKey ? t("apiKeyCreated") : t("createApiKey")}
              </DialogTitle>
            </DialogHeader>

            {newKey ? (
              <div className="space-y-4">
                <div className="p-4 bg-muted border border-border">
                  <p className="text-sm text-muted-foreground mb-2">
                    {t("copyWarning")}
                  </p>
                  <code className="block p-2 bg-background border text-xs break-all">
                    {newKey}
                  </code>
                </div>
                <Button
                  onClick={() => copyToClipboard(newKey)}
                  className="w-full"
                >
                  {t("copyToClipboard")}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => {
                    setIsCreateOpen(false);
                    setNewKey(null);
                  }}
                  className="w-full"
                >
                  {tc("close")}
                </Button>
              </div>
            ) : (
              <form action={handleCreate} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="organization_id">{t("organization")}</Label>
                  <select
                    id="organization_id"
                    name="organization_id"
                    required
                    value={selectedOrg}
                    onChange={(e) => setSelectedOrg(e.target.value)}
                    className="w-full p-2 border border-input bg-background"
                  >
                    <option value="">{t("selectOrg")}</option>
                    {organizations.map(org => (
                      <option key={org.id} value={org.id}>{org.name}</option>
                    ))}
                  </select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="user_id">{t("user")}</Label>
                  <select
                    id="user_id"
                    name="user_id"
                    required
                    disabled={!selectedOrg}
                    className="w-full p-2 border border-input bg-background"
                  >
                    <option value="">{t("selectUser")}</option>
                    {users.map(user => (
                      <option key={user.id} value={user.id}>{user.name}</option>
                    ))}
                  </select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="name">{t("keyName")}</Label>
                  <Input id="name" name="name" required placeholder={t("keyPlaceholder")} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="description">{t("description")}</Label>
                  <Input id="description" name="description" placeholder={t("descriptionPlaceholder")} />
                </div>
                <Button type="submit" className="w-full bg-primary text-primary-foreground">
                  {t("generateKey")}
                </Button>
              </form>
            )}
          </DialogContent>
        </Dialog>
      </div>

      <Card className="border-border">
        <CardContent className="pt-4">
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
        </CardContent>
      </Card>

      <Card className="border-border">
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow className="border-border">
                <TableHead>{t("tableHeaders.name")}</TableHead>
                <TableHead>{t("tableHeaders.prefix")}</TableHead>
                <TableHead>{t("tableHeaders.organization")}</TableHead>
                <TableHead>{t("tableHeaders.created")}</TableHead>
                <TableHead>{t("tableHeaders.lastUsed")}</TableHead>
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
              ) : apiKeys.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                    {t("noKeysFound")}
                  </TableCell>
                </TableRow>
              ) : (
                apiKeys.map((key) => (
                  <TableRow key={key.id} className="border-border">
                    <TableCell>
                      <div>
                        <span className="font-medium">{key.name}</span>
                        {key.description && (
                          <p className="text-xs text-muted-foreground">{key.description}</p>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <code className="text-xs bg-muted px-1 py-0.5">{key.key_prefix}...</code>
                    </TableCell>
                    <TableCell>{getOrgName(key.organization_id)}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDate(key.created_at)}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDate(key.last_used_at)}
                    </TableCell>
                    <TableCell>
                      <Badge variant={key.is_active ? "default" : "secondary"}>
                        {key.is_active ? t("active") : t("revoked")}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Button variant="ghost" size="sm" className="text-destructive">
                        {t("revoke")}
                      </Button>
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
    </div>
  );
}
